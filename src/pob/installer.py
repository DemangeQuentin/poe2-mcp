"""
Path of Building (PoE2) MCP Bridge — installation & detection.

This module is the Python counterpart to pob_addon/src/install.bat. It lets the
MCP server (and tests) do three things without a shell script:

  1. Detect where Path of Building (PoE2) is installed.
  2. Report whether the MCP Bridge addon is deployed AND whether Launch.lua is
     patched to load it.
  3. Install / uninstall the addon programmatically (idempotent, with backup).

The addon "injects" itself into PoB without modifying upstream source files in a
way that survives updates badly: it drops an ``Addons/`` folder (which PoB does
not ship) and adds ONE line to ``src/Launch.lua`` that ``dofile``s our loader.
That single line is what makes our TCP bridge come up inside PoB's Lua VM.

https://github.com/HivemindOverlord/poe2-mcp
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# The exact loader line install.bat injects into Launch.lua. Tab-indented to
# match PoB's source style. Detection keys off the "Addons/init.lua" substring,
# so the surrounding text can change without breaking idempotency.
ADDON_LOADER_LINE = (
    "\tpcall(dofile, GetScriptPath()..'/Addons/init.lua') "
    "-- MCP Bridge Addon Loader"
)
ADDON_LOADER_MARKER = "Addons/init.lua"

# Anchor we insert the loader after: the end of PoB's main-module Init block.
# This mirrors install.bat and is stable across PoB versions.
PATCH_ANCHOR = 'self:ShowErrMsg("In \'Init\': %s", errMsg)'


def _candidate_install_paths() -> List[Path]:
    """Common PoB (PoE2) install locations, mirroring install.bat plus the
    maintainer's dev clone documented in CLAUDE.md."""
    import os

    home = Path.home()
    candidates = [
        home / "Path of Building (PoE2)",
        Path(os.environ.get("LOCALAPPDATA", str(home))) / "Path of Building (PoE2)",
        Path("C:/Path of Building (PoE2)"),
        Path("C:/Program Files/Path of Building (PoE2)"),
        Path("C:/Program Files (x86)/Path of Building (PoE2)"),
        # PoE2-fork community builds sometimes install under these names:
        home / "Path of Building Community (PoE2)",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Path of Building (PoE2)",
        # Maintainer dev clone (CLAUDE.md "External File Locations").
        home / "ClaudesPathOfExile2EnhancementService" / "PathOfBuilding-PoE2",
    ]
    return candidates


def _is_pob_root(path: Path) -> bool:
    """A PoB install root contains src/Launch.lua."""
    try:
        return (path / "src" / "Launch.lua").is_file()
    except OSError:
        return False


def find_pob_installation(extra_paths: Optional[List[Path]] = None) -> Optional[Path]:
    """
    Locate a Path of Building (PoE2) installation.

    Args:
        extra_paths: Additional roots to check first (e.g. a user-supplied path
                     or the POB_PATH env var).

    Returns:
        The PoB install root (the folder whose ``src/Launch.lua`` exists), or
        None if no installation was found.
    """
    import os

    search: List[Path] = []
    if extra_paths:
        search.extend(Path(p) for p in extra_paths)
    env_path = os.environ.get("POB_PATH") or os.environ.get("POE2_POB_PATH")
    if env_path:
        search.append(Path(env_path))
    search.extend(_candidate_install_paths())

    for path in search:
        if _is_pob_root(path):
            logger.info("Found PoB installation: %s", path)
            return path
    logger.info("No PoB installation found in %d candidate paths", len(search))
    return None


def _bundled_addon_source() -> Optional[Path]:
    """
    Locate the addon source (the folder containing init.lua + MCPBridge/).

    Works from a source checkout (pob_addon/src/Addons) and from the packed
    .mcpb bundle, where the addon ships alongside the server tree.
    """
    here = Path(__file__).resolve()
    # src/pob/installer.py -> repo root is parents[2]
    candidates = [
        here.parents[2] / "pob_addon" / "src" / "Addons",   # source checkout
        here.parents[2] / "pob_addon" / "Addons",            # flattened bundle
        here.parents[1] / "pob_addon" / "Addons",            # server-root bundle
    ]
    for c in candidates:
        if (c / "init.lua").is_file() and (c / "MCPBridge" / "bridge.lua").is_file():
            return c
    return None


def is_addon_installed(pob_path: Path) -> Dict[str, object]:
    """
    Report addon deployment state for a given PoB install.

    Returns a dict with:
        files_present: bool  — Addons/MCPBridge/{bridge,commands,config}.lua exist
        launch_patched: bool — Launch.lua contains the loader line
        installed: bool      — both of the above (fully wired)
        missing: list[str]   — which expected files are absent
    """
    addons = pob_path / "src" / "Addons"
    expected = [
        addons / "init.lua",
        addons / "MCPBridge" / "bridge.lua",
        addons / "MCPBridge" / "commands.lua",
        addons / "MCPBridge" / "config.lua",
    ]
    missing = [str(p) for p in expected if not p.is_file()]
    files_present = not missing

    launch = pob_path / "src" / "Launch.lua"
    launch_patched = False
    if launch.is_file():
        try:
            launch_patched = ADDON_LOADER_MARKER in launch.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as e:
            logger.warning("Could not read Launch.lua: %s", e)

    return {
        "files_present": files_present,
        "launch_patched": launch_patched,
        "installed": files_present and launch_patched,
        "missing": missing,
    }


def _patch_launch_lua(launch: Path) -> str:
    """
    Idempotently insert the addon loader line into Launch.lua.

    Returns one of: "already_patched", "patched", "anchor_not_found".
    Caller is responsible for backups.
    """
    text = launch.read_text(encoding="utf-8", errors="replace")
    if ADDON_LOADER_MARKER in text:
        return "already_patched"

    lines = text.splitlines(keepends=True)
    anchor_idx = next(
        (i for i, ln in enumerate(lines) if PATCH_ANCHOR in ln), None
    )
    if anchor_idx is None:
        return "anchor_not_found"

    # Insert after the `end` that closes the `if errMsg then` block following the
    # anchor (matches install.bat). Fall back to right after the anchor line.
    insert_at = anchor_idx + 1
    for j in range(anchor_idx + 1, min(anchor_idx + 4, len(lines))):
        if lines[j].strip() == "end":
            insert_at = j + 1
            break

    newline = "\n"
    if lines and lines[insert_at - 1].endswith("\r\n"):
        newline = "\r\n"
    lines.insert(insert_at, ADDON_LOADER_LINE + newline)
    launch.write_text("".join(lines), encoding="utf-8")
    return "patched"


def install_addon(
    pob_path: Optional[Path] = None,
    source_dir: Optional[Path] = None,
    overwrite: bool = True,
) -> Dict[str, object]:
    """
    Install the MCP Bridge addon into a PoB (PoE2) installation.

    Args:
        pob_path: PoB install root. Auto-detected if omitted.
        source_dir: Addon source (folder with init.lua + MCPBridge/). Auto-located
                    from the repo/bundle if omitted.
        overwrite: Re-copy addon files even if already present.

    Returns:
        Result dict: {success, pob_path, launch_patch, message}. On failure,
        success is False and message explains why.
    """
    if pob_path is None:
        pob_path = find_pob_installation()
    if pob_path is None:
        return {
            "success": False,
            "message": "Path of Building installation not found. "
            "Set POB_PATH or pass pob_path explicitly.",
        }
    pob_path = Path(pob_path)
    if not _is_pob_root(pob_path):
        return {
            "success": False,
            "message": f"Not a PoB install (no src/Launch.lua): {pob_path}",
        }

    if source_dir is None:
        source_dir = _bundled_addon_source()
    if source_dir is None or not (Path(source_dir) / "init.lua").is_file():
        return {
            "success": False,
            "message": "Addon source files not found (expected pob_addon/src/Addons).",
        }
    source_dir = Path(source_dir)

    src_addons = pob_path / "src" / "Addons"
    try:
        # Copy init.lua + MCPBridge/ into PoB's src/Addons.
        (src_addons / "MCPBridge").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / "init.lua", src_addons / "init.lua")
        for name in ("bridge.lua", "commands.lua", "config.lua"):
            src = source_dir / "MCPBridge" / name
            if src.is_file():
                shutil.copy2(src, src_addons / "MCPBridge" / name)
    except OSError as e:
        return {
            "success": False,
            "message": f"Failed to copy addon files (permissions? PoB in Program "
            f"Files needs admin): {e}",
        }

    # Back up Launch.lua once, then patch.
    launch = pob_path / "src" / "Launch.lua"
    backup = pob_path / "src" / "Launch.lua.mcp_backup"
    try:
        if not backup.exists():
            shutil.copy2(launch, backup)
        patch_result = _patch_launch_lua(launch)
    except OSError as e:
        return {
            "success": False,
            "message": f"Failed to patch Launch.lua: {e}",
        }

    if patch_result == "anchor_not_found":
        return {
            "success": False,
            "pob_path": str(pob_path),
            "launch_patch": patch_result,
            "message": "Addon files copied, but could not find the Launch.lua "
            "anchor to inject the loader. PoB version may have changed; "
            "patch manually (see pob_addon/README.md).",
        }

    return {
        "success": True,
        "pob_path": str(pob_path),
        "launch_patch": patch_result,
        "message": "MCP Bridge addon installed. Restart Path of Building; it will "
        "listen on 127.0.0.1:49085.",
    }


def uninstall_addon(pob_path: Optional[Path] = None) -> Dict[str, object]:
    """
    Remove the addon and restore Launch.lua from backup (or strip the loader line).
    """
    if pob_path is None:
        pob_path = find_pob_installation()
    if pob_path is None:
        return {"success": False, "message": "PoB installation not found."}
    pob_path = Path(pob_path)

    # Remove addon files.
    addons = pob_path / "src" / "Addons" / "MCPBridge"
    removed = []
    if addons.exists():
        shutil.rmtree(addons, ignore_errors=True)
        removed.append(str(addons))
    init_lua = pob_path / "src" / "Addons" / "init.lua"
    if init_lua.exists():
        init_lua.unlink()
        removed.append(str(init_lua))

    # Restore Launch.lua from backup if present, else strip the loader line.
    launch = pob_path / "src" / "Launch.lua"
    backup = pob_path / "src" / "Launch.lua.mcp_backup"
    if backup.exists():
        shutil.copy2(backup, launch)
    elif launch.is_file():
        text = launch.read_text(encoding="utf-8", errors="replace")
        kept = [ln for ln in text.splitlines(keepends=True)
                if ADDON_LOADER_MARKER not in ln]
        launch.write_text("".join(kept), encoding="utf-8")

    return {
        "success": True,
        "pob_path": str(pob_path),
        "removed": removed,
        "message": "MCP Bridge addon uninstalled. Restart Path of Building.",
    }


def get_bridge_status(
    host: str = "127.0.0.1",
    port: int = 49085,
    pob_path: Optional[Path] = None,
) -> Dict[str, object]:
    """
    One-shot status: is PoB installed, is the addon deployed, and is the live
    bridge reachable right now?

    This is the data backing the ``pob_status`` MCP tool. It never raises.
    """
    if pob_path is None:
        pob_path = find_pob_installation()

    result: Dict[str, object] = {
        "pob_installed": pob_path is not None,
        "pob_path": str(pob_path) if pob_path else None,
        "addon_installed": False,
        "launch_patched": False,
        "bridge_reachable": False,
        "ping": None,
    }

    if pob_path is not None:
        deploy = is_addon_installed(Path(pob_path))
        result["addon_installed"] = deploy["installed"]
        result["launch_patched"] = deploy["launch_patched"]

    # Probe the live bridge regardless of detected install (user may run a
    # custom path). Import here to avoid a hard dependency cycle.
    try:
        from .client import PoBClient
    except ImportError:  # pragma: no cover - direct execution fallback
        from src.pob.client import PoBClient  # type: ignore

    try:
        client = PoBClient(host=host, port=port, timeout=2.0)
        ping = client.ping()
        result["bridge_reachable"] = ping.get("status") == "ok"
        result["ping"] = ping
    except Exception as e:  # noqa: BLE001 - status must never raise
        result["ping_error"] = str(e)

    return result
