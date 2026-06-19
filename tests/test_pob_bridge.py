"""
Offline unit tests for the live Path of Building bridge.

Unlike test_pob_integration.py (which needs a real PoB running), these tests
use a mock TCP server and temp directories, so they run in CI with no PoB and
no network. They cover:

  * PoBClient JSON-RPC round-trips (ping / get_passive_tree / get_build /
    load_build / get_calcs) against a mock server speaking the addon's protocol.
  * installer.py: install detection, Launch.lua patch idempotency, and
    install/uninstall against a fake PoB tree.
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from src.pob.client import PoBClient, PoBCommandError
from src.pob import installer

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_SOURCE = REPO_ROOT / "pob_addon" / "src" / "Addons"


# ---------------------------------------------------------------------------
# Mock bridge server (mimics pob_addon/src/Addons/MCPBridge/bridge.lua)
# ---------------------------------------------------------------------------

# Canned responses keyed by JSON-RPC method, matching what commands.lua returns.
MOCK_RESPONSES = {
    "ping": {
        "status": "ok",
        "version": "1.1.0",
        "pob_version": "0.20.0",
        "build_loaded": True,
        "build_name": "Mock Build",
        "uptime": 1,
    },
    "get_passive_tree": {
        "class": "Ranger",
        "classId": 2,
        "ascendancy": "Deadeye",
        "ascendancyId": 1,
        "nodes": [{"id": 50459, "name": "RANGER", "type": "ClassStart", "stats": []}],
        "totalPoints": 1,
    },
    "get_build": {"code": "eNrMOCKCODE", "format": "pob_code", "name": "Mock Build"},
    "get_calcs": {"TotalDPS": 123456.0, "Life": 4200, "FireResist": 75},
    "load_build": {"success": True, "name": "Mock Import", "note": "queued"},
}


class MockBridgeServer:
    """Single-threaded mock that accepts one connection per request (like the
    real addon — PoBClient opens a fresh socket per command)."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))  # ephemeral port
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self.last_request = None

    def start(self):
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                client.settimeout(1.0)
                buf = b""
                while b"\n" not in buf:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                req = json.loads(buf.decode("utf-8").strip())
                self.last_request = req
                method = req.get("method")
                if method in MOCK_RESPONSES:
                    payload = {"jsonrpc": "2.0", "id": req.get("id"),
                               "result": MOCK_RESPONSES[method]}
                else:
                    payload = {"jsonrpc": "2.0", "id": req.get("id"),
                               "error": {"code": -32601, "message": f"Method not found: {method}"}}
                client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            except Exception:
                pass
            finally:
                client.close()

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)


@pytest.fixture
def mock_bridge():
    server = MockBridgeServer()
    server.start()
    yield server
    server.stop()


# ---------------------------------------------------------------------------
# PoBClient round-trip tests
# ---------------------------------------------------------------------------

def test_client_ping(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    assert client.is_connected() is True
    ping = client.ping()
    assert ping["status"] == "ok"
    assert ping["build_loaded"] is True


def test_client_get_passive_tree(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    tree = client.get_passive_tree()
    assert tree["class"] == "Ranger"
    assert tree["totalPoints"] == 1
    assert tree["nodes"][0]["id"] == 50459


def test_client_get_build_code(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    build = client.get_build(format="code")
    assert build["code"].startswith("eNr")
    # Verify the request actually asked for code format
    assert mock_bridge.last_request["params"]["format"] == "code"


def test_client_load_build_roundtrip(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    result = client.load_build(code="eNrSOMECODE", name="Mock Import")
    assert result["success"] is True
    assert mock_bridge.last_request["method"] == "load_build"
    assert mock_bridge.last_request["params"]["code"] == "eNrSOMECODE"


def test_client_get_calcs(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    calcs = client.get_calcs()
    assert calcs["TotalDPS"] == pytest.approx(123456.0)
    assert calcs["Life"] == 4200


def test_client_unknown_method_raises(mock_bridge):
    client = PoBClient(port=mock_bridge.port, timeout=2.0)
    with pytest.raises(PoBCommandError):
        client._send_command("does_not_exist")


def test_client_not_connected_when_no_server():
    # Nothing listening on this port -> is_connected False, never raises
    client = PoBClient(port=59999, timeout=0.5)
    assert client.is_connected() is False


# ---------------------------------------------------------------------------
# Installer tests (fake PoB tree in a tmp dir)
# ---------------------------------------------------------------------------

# A minimal Launch.lua containing the real patch anchor + surrounding block.
FAKE_LAUNCH_LUA = """\
function launch:OnInit()
\tlocal errMsg
\terrMsg, self.main = PLoadModule("Modules/Main")
\tif errMsg then
\t\tself:ShowErrMsg("Error loading main script: %s", errMsg)
\telseif self.main.Init then
\t\terrMsg = PCall(self.main.Init, self.main)
\t\tif errMsg then
\t\t\tself:ShowErrMsg("In 'Init': %s", errMsg)
\t\tend
\tend
end
"""


@pytest.fixture
def fake_pob(tmp_path):
    root = tmp_path / "PathOfBuilding-PoE2"
    (root / "src").mkdir(parents=True)
    (root / "src" / "Launch.lua").write_text(FAKE_LAUNCH_LUA, encoding="utf-8")
    return root


def test_find_pob_installation(fake_pob):
    found = installer.find_pob_installation(extra_paths=[fake_pob])
    assert found == fake_pob


def test_non_pob_dir_not_detected(tmp_path):
    # A dir with no src/Launch.lua is not a PoB root. (We assert on _is_pob_root
    # rather than find_pob_installation, which intentionally falls back to
    # scanning common install paths and would find a real install on a dev box.)
    assert installer._is_pob_root(tmp_path) is False
    assert installer._is_pob_root(tmp_path / "nope") is False


def test_addon_source_resolves():
    assert ADDON_SOURCE.is_dir()
    assert (ADDON_SOURCE / "init.lua").is_file()
    assert (ADDON_SOURCE / "MCPBridge" / "bridge.lua").is_file()


def test_install_and_detect(fake_pob):
    before = installer.is_addon_installed(fake_pob)
    assert before["installed"] is False
    assert before["launch_patched"] is False

    result = installer.install_addon(pob_path=fake_pob, source_dir=ADDON_SOURCE)
    assert result["success"] is True, result
    assert result["launch_patch"] in ("patched", "already_patched")

    after = installer.is_addon_installed(fake_pob)
    assert after["installed"] is True
    assert after["files_present"] is True
    assert after["launch_patched"] is True

    # Loader line landed in Launch.lua exactly once
    launch_text = (fake_pob / "src" / "Launch.lua").read_text(encoding="utf-8")
    assert launch_text.count(installer.ADDON_LOADER_MARKER) == 1
    # Backup was created
    assert (fake_pob / "src" / "Launch.lua.mcp_backup").is_file()


def test_patch_idempotent(fake_pob):
    installer.install_addon(pob_path=fake_pob, source_dir=ADDON_SOURCE)
    # Re-running install must not duplicate the loader line
    installer.install_addon(pob_path=fake_pob, source_dir=ADDON_SOURCE)
    launch_text = (fake_pob / "src" / "Launch.lua").read_text(encoding="utf-8")
    assert launch_text.count(installer.ADDON_LOADER_MARKER) == 1

    # Direct patch call on an already-patched file reports already_patched
    status = installer._patch_launch_lua(fake_pob / "src" / "Launch.lua")
    assert status == "already_patched"


def test_patch_anchor_not_found(tmp_path):
    root = tmp_path / "NoAnchorPoB"
    (root / "src").mkdir(parents=True)
    (root / "src" / "Launch.lua").write_text("function launch:OnInit() end\n", encoding="utf-8")
    result = installer.install_addon(pob_path=root, source_dir=ADDON_SOURCE)
    # Files copy, but patch can't find the anchor -> reported, not silently OK
    assert result["success"] is False
    assert result["launch_patch"] == "anchor_not_found"


def test_uninstall_restores(fake_pob):
    installer.install_addon(pob_path=fake_pob, source_dir=ADDON_SOURCE)
    original = FAKE_LAUNCH_LUA

    result = installer.uninstall_addon(pob_path=fake_pob)
    assert result["success"] is True

    # Addon files gone
    assert not (fake_pob / "src" / "Addons" / "MCPBridge").exists()
    # Launch.lua restored from backup (loader line stripped)
    launch_text = (fake_pob / "src" / "Launch.lua").read_text(encoding="utf-8")
    assert installer.ADDON_LOADER_MARKER not in launch_text
    assert launch_text == original


def test_config_lua_uses_global_mcpconfig():
    """Regression guard for the bug that kept the bridge from ever binding:
    config.lua must declare MCPConfig as a GLOBAL, not local."""
    config_lua = (ADDON_SOURCE / "MCPBridge" / "config.lua").read_text(encoding="utf-8")
    assert "local MCPConfig" not in config_lua
    assert "MCPConfig = {}" in config_lua
