"""
Tests for the permissioned self-update layer.

Locks the consent model added alongside the check_for_updates MCP tool:
  1. consent_mode() derives 'off'/'auto'/'notify' correctly from env vars.
  2. ensure_data_current() gates UPGRADES behind consent but always allows
     a fresh-install BOOTSTRAP (no local data).
  3. update_manager.get_update_status() aggregates both layers without raising.

All network/git/download calls are monkeypatched — these tests never touch
the network or the real git repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data import data_distributor as dd  # noqa: E402
from src.data import update_manager as um  # noqa: E402


# ---------------------------------------------------------------------------
# consent_mode
# ---------------------------------------------------------------------------
def test_consent_mode_default_is_notify(monkeypatch):
    for var in ("POE2_MCP_AUTO_UPDATE", "POE2_MCP_NO_DATA_FETCH", "POE2_MCP_NO_CODE_CHECK"):
        monkeypatch.delenv(var, raising=False)
    assert um.consent_mode("data") == "notify"
    assert um.consent_mode("code") == "notify"


def test_consent_mode_auto(monkeypatch):
    monkeypatch.setenv("POE2_MCP_AUTO_UPDATE", "1")
    monkeypatch.delenv("POE2_MCP_NO_DATA_FETCH", raising=False)
    monkeypatch.delenv("POE2_MCP_NO_CODE_CHECK", raising=False)
    assert um.consent_mode("data") == "auto"
    assert um.consent_mode("code") == "auto"


def test_consent_mode_off_per_layer(monkeypatch):
    monkeypatch.setenv("POE2_MCP_NO_DATA_FETCH", "1")
    monkeypatch.setenv("POE2_MCP_NO_CODE_CHECK", "1")
    monkeypatch.delenv("POE2_MCP_AUTO_UPDATE", raising=False)
    assert um.consent_mode("data") == "off"
    assert um.consent_mode("code") == "off"


# ---------------------------------------------------------------------------
# ensure_data_current consent gating
# ---------------------------------------------------------------------------
def _patch_data_env(monkeypatch):
    """Clear the env so consent derives purely from the call arg."""
    monkeypatch.delenv("POE2_MCP_NO_DATA_FETCH", raising=False)
    monkeypatch.delenv("POE2_MCP_AUTO_UPDATE", raising=False)


def test_upgrade_blocked_without_consent(monkeypatch):
    """Stale local data + no consent => report only, no download."""
    _patch_data_env(monkeypatch)
    monkeypatch.setattr(dd, "needs_update", lambda: (True, "local 'data-v0.5.0-1' != latest 'data-v0.5.0-2'"))
    monkeypatch.setattr(dd, "get_local_data_version", lambda: {"release_tag": "data-v0.5.0-1"})
    called = {"download": False}
    monkeypatch.setattr(dd, "get_latest_release_info", lambda: {"tag_name": "data-v0.5.0-2"})
    monkeypatch.setattr(dd, "download_and_install", lambda rel: called.__setitem__("download", True) or True)

    ok, msg = dd.ensure_data_current(consent=False)
    assert ok is True  # runnable on local data
    assert called["download"] is False
    assert "not applied without consent" in msg


def test_upgrade_applied_with_consent(monkeypatch):
    """Stale local data + consent => download happens."""
    _patch_data_env(monkeypatch)
    monkeypatch.setattr(dd, "needs_update", lambda: (True, "stale"))
    monkeypatch.setattr(dd, "get_local_data_version", lambda: {"release_tag": "data-v0.5.0-1"})
    monkeypatch.setattr(dd, "get_latest_release_info", lambda: {"tag_name": "data-v0.5.0-2"})
    called = {"download": False}
    monkeypatch.setattr(dd, "download_and_install", lambda rel: called.__setitem__("download", True) or True)

    ok, msg = dd.ensure_data_current(consent=True)
    assert ok is True
    assert called["download"] is True
    assert "updated to data-v0.5.0-2" in msg


def test_bootstrap_always_downloads(monkeypatch):
    """No local data => download proceeds even with consent=False."""
    _patch_data_env(monkeypatch)
    monkeypatch.setattr(dd, "needs_update", lambda: (True, "no local data/version.json (fresh install)"))
    monkeypatch.setattr(dd, "get_local_data_version", lambda: None)
    monkeypatch.setattr(dd, "get_latest_release_info", lambda: {"tag_name": "data-v0.5.0-1"})
    called = {"download": False}
    monkeypatch.setattr(dd, "download_and_install", lambda rel: called.__setitem__("download", True) or True)

    ok, msg = dd.ensure_data_current(consent=False)
    assert ok is True
    assert called["download"] is True  # bootstrap overrides lack of consent


def test_no_data_fetch_env_short_circuits(monkeypatch):
    monkeypatch.setenv("POE2_MCP_NO_DATA_FETCH", "1")
    # needs_update should never be consulted; make it explode if it is.
    monkeypatch.setattr(dd, "needs_update", lambda: (_ for _ in ()).throw(AssertionError("should not run")))
    ok, msg = dd.ensure_data_current()
    assert ok is True
    assert "POE2_MCP_NO_DATA_FETCH" in msg


def test_consent_derived_from_env_when_none(monkeypatch):
    """consent=None + POE2_MCP_AUTO_UPDATE=1 => behaves as consent=True."""
    monkeypatch.delenv("POE2_MCP_NO_DATA_FETCH", raising=False)
    monkeypatch.setenv("POE2_MCP_AUTO_UPDATE", "1")
    monkeypatch.setattr(dd, "needs_update", lambda: (True, "stale"))
    monkeypatch.setattr(dd, "get_local_data_version", lambda: {"release_tag": "old"})
    monkeypatch.setattr(dd, "get_latest_release_info", lambda: {"tag_name": "new"})
    called = {"download": False}
    monkeypatch.setattr(dd, "download_and_install", lambda rel: called.__setitem__("download", True) or True)

    ok, _ = dd.ensure_data_current()  # consent=None -> env
    assert called["download"] is True


# ---------------------------------------------------------------------------
# update_manager aggregation
# ---------------------------------------------------------------------------
def test_get_update_status_offline_shape(monkeypatch):
    """With network off, status still returns a well-formed dict, no raise."""
    for var in ("POE2_MCP_AUTO_UPDATE", "POE2_MCP_NO_DATA_FETCH", "POE2_MCP_NO_CODE_CHECK"):
        monkeypatch.delenv(var, raising=False)
    status = um.get_update_status(allow_network=False)
    assert set(status) >= {"update_available", "data", "code", "recommended_action"}
    assert status["data"]["layer"] == "data"
    assert status["code"]["layer"] == "code"
    assert isinstance(status["recommended_action"], str)


def test_recommend_clean_when_current():
    data = {"update_available": False, "is_bootstrap": False, "latest_tag": None,
            "consent_mode": "notify"}
    code = {"update_available": False, "install_kind": "git", "can_self_apply": True,
            "consent_mode": "notify", "latest": None}
    assert um._recommend(data, code) == "Everything is current."


def test_recommend_packaged_points_to_reinstall():
    data = {"update_available": False, "is_bootstrap": False, "latest_tag": None,
            "consent_mode": "notify"}
    code = {"update_available": True, "install_kind": "packaged", "can_self_apply": False,
            "consent_mode": "notify", "latest": "mcpb-latest"}
    msg = um._recommend(data, code)
    assert "reinstall" in msg.lower()
