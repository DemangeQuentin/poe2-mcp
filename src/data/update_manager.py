"""Permissioned self-update orchestration for the PoE2 MCP server.

The server has two independently-updatable layers:

  * **Game data** — the curated `.datc64`-extracted JSON bundle distributed as
    `poe2-data.zip` via GitHub Releases (see `data_distributor`).
  * **Code** — the MCP server itself. How it updates depends on how it was
    installed: a *git checkout* fast-forwards `main`; a *packaged* install
    (the `.mcpb` Claude Desktop bundle, or pip) is replaced by reinstalling a
    newer artifact, which the running process cannot do to itself.

Consent model
=============
Updates are NEVER applied silently. A single env var sets the standing policy:

  * ``POE2_MCP_AUTO_UPDATE=1``  -> ``auto``   : permission granted ahead of time;
                                                stale data/code applied on launch.
  * (default)                   -> ``notify`` : check + report, never auto-apply.
  * ``POE2_MCP_NO_DATA_FETCH=1`` / ``POE2_MCP_NO_CODE_CHECK=1`` -> ``off`` per layer.

Interactive permission is also possible at runtime: the ``check_for_updates``
MCP tool reports status, and invoking it with ``apply=true`` IS the user's
explicit consent to apply right then.

Bootstrap exception
===================
A *fresh* install with no game data at all cannot function. Acquiring data for
the first time is treated as bootstrap (the act of installing the MCP is consent
to fetch the data it needs) and is always allowed. Only *upgrading* already-
working data to a newer release is gated behind consent.

Per CLAUDE.md data policy: the only external data source is this repo's own
GitHub Releases bundle. Code update checks hit only the GitHub API / origin.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (normal runtime)
    from . import data_distributor as _dd
except ImportError:  # direct-execution fallback
    import data_distributor as _dd  # type: ignore

logger = logging.getLogger(__name__)

GITHUB_REPO = _dd.GITHUB_REPO
RELEASES_API = _dd.RELEASES_API

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_MANIFEST_FILE = _BASE_DIR / "mcpb_bundle" / "manifest.json"


# ---------------------------------------------------------------------------
# Consent policy
# ---------------------------------------------------------------------------
def consent_mode(layer: str) -> str:
    """Return the standing consent policy for ``layer`` ('data' or 'code').

    One of: ``'off'`` (don't even check), ``'auto'`` (apply without asking),
    ``'notify'`` (check + report, the default). Derived purely from env so the
    policy is identical whether read at launch or inside an MCP handler.
    """
    if layer == "data" and os.environ.get("POE2_MCP_NO_DATA_FETCH"):
        return "off"
    if layer == "code" and os.environ.get("POE2_MCP_NO_CODE_CHECK") == "1":
        return "off"
    if os.environ.get("POE2_MCP_AUTO_UPDATE") == "1":
        return "auto"
    return "notify"


# ---------------------------------------------------------------------------
# Install-kind detection
# ---------------------------------------------------------------------------
def _git(*args: str, timeout: int = 10) -> Optional[str]:
    """Run a git command at the repo root; return stripped stdout or None."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        out = subprocess.run(
            [git, "-C", str(_BASE_DIR), *args],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def detect_install_kind() -> str:
    """Classify how this server was installed: 'git', 'packaged', or 'unknown'.

    A git checkout has a working `.git` and resolves a toplevel. Anything else
    (the .mcpb bundle, a pip install) is 'packaged' — it can detect newer
    versions but must be replaced externally, not self-modified.
    """
    if (_BASE_DIR / ".git").exists() and _git("rev-parse", "--show-toplevel"):
        return "git"
    if _MANIFEST_FILE.exists() or (_BASE_DIR / "server").exists():
        return "packaged"
    return "packaged"  # default: assume we can't self-modify code


def _packaged_code_version() -> Optional[str]:
    """Best-effort current code version for a packaged install (manifest)."""
    if _MANIFEST_FILE.exists():
        try:
            return json.loads(_MANIFEST_FILE.read_text(encoding="utf-8")).get("version")
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _latest_code_release() -> Optional[Dict[str, Any]]:
    """Newest GitHub release that is NOT a `data-*` bundle (i.e. a code build).

    Includes prereleases (the rolling `mcpb-latest` build) so packaged users
    learn when a fresher Desktop bundle is available. Returns the raw release
    dict or None.
    """
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"User-Agent": "poe2-mcp-update-manager",
                     "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            releases = json.loads(r.read())
    except Exception as e:  # network failure is non-fatal
        logger.warning("Failed to query GitHub Releases for code version: %s", e)
        return None
    for rel in releases:
        if rel.get("draft"):
            continue
        if not str(rel.get("tag_name", "")).startswith("data-"):
            return rel
    return None


# ---------------------------------------------------------------------------
# Status aggregation
# ---------------------------------------------------------------------------
def get_data_status(allow_network: bool = True) -> Dict[str, Any]:
    """Summarize game-data freshness using data_distributor."""
    local = _dd.get_local_data_version()
    local_tag = (local or {}).get("release_tag")
    status: Dict[str, Any] = {
        "layer": "data",
        "consent_mode": consent_mode("data"),
        "local_tag": local_tag,
        "is_bootstrap": local is None,
        "latest_tag": None,
        "update_available": False,
        "reason": "",
    }
    if not allow_network or status["consent_mode"] == "off":
        status["reason"] = "freshness check skipped (network off or POE2_MCP_NO_DATA_FETCH)"
        return status
    remote = _dd.get_latest_release_info()
    if remote:
        status["latest_tag"] = remote.get("tag_name")
    update, reason = _dd.needs_update()
    status["update_available"] = update
    status["reason"] = reason
    return status


def get_code_status(allow_network: bool = True) -> Dict[str, Any]:
    """Summarize code freshness, branching on install kind."""
    kind = detect_install_kind()
    status: Dict[str, Any] = {
        "layer": "code",
        "install_kind": kind,
        "consent_mode": consent_mode("code"),
        "update_available": False,
        "can_self_apply": kind == "git",
        "current": None,
        "latest": None,
        "reason": "",
    }
    if status["consent_mode"] == "off":
        status["reason"] = "code check disabled (POE2_MCP_NO_CODE_CHECK=1)"
        return status

    if kind == "git":
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        status["current"] = _git("rev-parse", "--short", "HEAD")
        if branch != "main":
            status["reason"] = f"on branch '{branch}' (not main); not tracking updates"
            status["can_self_apply"] = False
            return status
        if not allow_network:
            status["reason"] = "network off; cannot compare to origin/main"
            return status
        if _git("fetch", "--quiet", "origin", "main", timeout=30) is None:
            status["reason"] = "could not fetch origin (offline?)"
            return status
        remote_head = _git("rev-parse", "origin/main")
        local_head = _git("rev-parse", "HEAD")
        if remote_head and local_head and remote_head != local_head:
            behind = _git("rev-list", "--count", f"{local_head}..{remote_head}") or "?"
            dirty = bool(_git("status", "--porcelain"))
            status["update_available"] = True
            status["latest"] = remote_head[:7] if remote_head else None
            status["can_self_apply"] = not dirty
            status["reason"] = (
                f"{behind} commit(s) behind origin/main"
                + ("; working tree dirty (manual pull needed)" if dirty else "")
            )
        else:
            status["reason"] = "up to date with origin/main"
        return status

    # packaged (.mcpb / pip): can detect, cannot self-replace
    status["current"] = _packaged_code_version()
    if not allow_network:
        status["reason"] = "network off; cannot check for newer build"
        return status
    rel = _latest_code_release()
    if rel:
        status["latest"] = rel.get("tag_name")
        # Packaged installs can't reliably semver-compare a rolling tag, so we
        # only flag availability; the user decides whether to reinstall.
        status["update_available"] = True
        status["reason"] = (
            f"latest published build is '{rel.get('tag_name')}' — reinstall the "
            f".mcpb to update (a running packaged server can't replace itself)"
        )
    else:
        status["reason"] = "no published code release found"
    return status


def get_update_status(allow_network: bool = True) -> Dict[str, Any]:
    """Full update picture across both layers, plus a recommended action."""
    data = get_data_status(allow_network)
    code = get_code_status(allow_network)
    any_update = bool(data["update_available"] or code["update_available"])
    return {
        "update_available": any_update,
        "data": data,
        "code": code,
        "recommended_action": _recommend(data, code),
    }


def _recommend(data: Dict[str, Any], code: Dict[str, Any]) -> str:
    """Human-readable next step given the two layer statuses."""
    parts: List[str] = []
    if data["update_available"]:
        if data["is_bootstrap"]:
            parts.append("game data missing — will bootstrap on launch")
        elif data["consent_mode"] == "auto":
            parts.append(f"data update {data['latest_tag']} will apply automatically")
        else:
            parts.append(
                f"data update {data['latest_tag']} available — call check_for_updates "
                f"with apply=true, or set POE2_MCP_AUTO_UPDATE=1"
            )
    if code["update_available"]:
        if code["install_kind"] == "git" and code["can_self_apply"]:
            if code["consent_mode"] == "auto":
                parts.append("code will fast-forward on next launch")
            else:
                parts.append(
                    "code update available — call check_for_updates with apply=true, "
                    "or set POE2_MCP_AUTO_UPDATE=1 to auto fast-forward"
                )
        elif code["install_kind"] == "git":
            parts.append("code behind but working tree dirty — `git pull` manually")
        else:
            parts.append(f"newer build '{code['latest']}' — reinstall the .mcpb to update")
    if not parts:
        return "Everything is current."
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Application (only with consent)
# ---------------------------------------------------------------------------
def _ensure_data(consent: bool) -> Dict[str, Any]:
    """Apply a pending data update if consented (bootstrap always proceeds)."""
    ok, msg = _dd.ensure_data_current(consent=consent)
    return {"ok": ok, "message": msg}


def apply_code_update(consent: bool) -> Dict[str, Any]:
    """Fast-forward the git checkout to origin/main if consented and safe.

    Packaged installs return guidance (a running bundle cannot replace itself).
    """
    code = get_code_status(allow_network=True)
    if not code["update_available"]:
        return {"ok": True, "message": code["reason"]}
    if code["install_kind"] != "git":
        return {"ok": False, "message": code["reason"]}
    if not consent:
        return {"ok": False, "message": "code update available but consent not given"}
    if not code["can_self_apply"]:
        return {"ok": False, "message": code["reason"]}
    if _git("merge", "--ff-only", "origin/main", timeout=30) is None:
        return {"ok": False, "message": "fast-forward failed; pull manually"}
    return {"ok": True, "message": f"fast-forwarded to {code['latest']}"}


def apply_updates(consent: bool, data: bool = True, code: bool = True) -> Dict[str, Any]:
    """Apply pending updates across requested layers. Consent is mandatory.

    Returns a dict with per-layer results. ``consent`` False is honored for the
    *upgrade* path; data bootstrap (no local data) still proceeds since the MCP
    is non-functional without it.
    """
    results: Dict[str, Any] = {"data": None, "code": None}
    if data:
        results["data"] = _ensure_data(consent)
    if code:
        results["code"] = apply_code_update(consent)
    results["ok"] = all(
        (r is None) or r.get("ok", False) for r in (results["data"], results["code"])
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(json.dumps(get_update_status(), indent=2))
