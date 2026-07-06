"""
Tests for the opt-in error reporter (`report_error` tool + src/error_reporter.py).

Focus: privacy by construction (no argument values ever captured), the buffer
semantics, the prefilled-link builders, and the MCP handler's no-account
local-file floor.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import mcp.types as types

from src.error_reporter import (
    REPORT_EMAIL,
    ErrorRecorder,
    build_report,
    github_issue_link,
    mailto_link,
    report_to_text,
)
from src.mcp_server import PoE2BuildOptimizerMCP


def _err(text: str):
    return [types.TextContent(type="text", text=text)]


# --------------------------------------------------------------------------- #
# ErrorRecorder — capture + redaction
# --------------------------------------------------------------------------- #


def test_records_only_error_prefixed_results():
    rec = ErrorRecorder()
    rec.observe("t", {}, _err("Success: all good"))
    assert rec.count() == 0
    rec.observe("t", {}, _err("Error: boom"))
    assert rec.count() == 1


def test_stores_arg_keys_never_values():
    rec = ErrorRecorder()
    rec.observe(
        "inspect_spell_gem",
        {"spell_name": "Fireball", "account": "SecretUser#1234"},
        _err("Error: not found"),
    )
    captured = rec.recent()[0]
    assert captured["arg_keys"] == ["account", "spell_name"]
    # No value should appear anywhere in the captured record.
    blob = json.dumps(captured)
    assert "Fireball" not in blob
    assert "SecretUser" not in blob


def test_message_is_length_capped():
    rec = ErrorRecorder()
    rec.observe("t", {}, _err("Error: " + "x" * 5000))
    assert len(rec.recent()[0]["message"]) <= 600


def test_buffer_is_bounded():
    rec = ErrorRecorder(maxlen=3)
    for i in range(10):
        rec.observe("t", {}, _err(f"Error: {i}"))
    assert rec.count() == 3
    # Keeps the most recent.
    assert rec.recent()[-1]["message"] == "Error: 9"


def test_recent_limit_and_clear():
    rec = ErrorRecorder()
    for i in range(5):
        rec.observe("t", {}, _err(f"Error: {i}"))
    assert len(rec.recent(2)) == 2
    rec.clear()
    assert rec.count() == 0


# --------------------------------------------------------------------------- #
# Report + link builders
# --------------------------------------------------------------------------- #


def test_build_report_shape_and_env():
    report = build_report(
        [{"ts": "x", "tool": "t", "arg_keys": [], "message": "Error: y"}], note="hi"
    )
    assert report["error_count"] == 1
    assert report["user_note"] == "hi"
    assert "python" in report["env"] and "platform" in report["env"]


def test_mailto_link_targets_alias_and_encodes_body():
    report = build_report(
        [{"ts": "x", "tool": "t", "arg_keys": [], "message": "Error: boom & <fail>"}]
    )
    link = mailto_link(report)
    assert link.startswith(f"mailto:{REPORT_EMAIL}?subject=")
    assert "&body=" in link
    # raw special chars must be percent-encoded, not literal, in the body
    assert "<fail>" not in link
    assert "%3Cfail%3E" in link


def test_github_issue_link_prefills_label_and_repo():
    report = build_report([{"ts": "x", "tool": "t", "arg_keys": [], "message": "Error: boom"}])
    link = github_issue_link(report)
    assert link.startswith("https://github.com/HivemindOverlord/poe2-mcp/issues/new")
    assert "labels=mcp-error-report" in link
    assert "title=" in link and "body=" in link


def test_report_text_plain_and_markdown():
    report = build_report(
        [{"ts": "2026", "tool": "inspect_mod", "arg_keys": ["mod_name"], "message": "Error: nope"}],
        note="broke",
    )
    plain = report_to_text(report, markdown=False)
    assert "inspect_mod" in plain and "mod_name" in plain and "broke" in plain
    md = report_to_text(report, markdown=True)
    assert md.strip().endswith("```")


# --------------------------------------------------------------------------- #
# MCP handler — the no-account local-file floor
# --------------------------------------------------------------------------- #


@pytest.fixture
def server():
    return PoE2BuildOptimizerMCP()


@pytest.mark.asyncio
async def test_report_error_tool_is_registered(server):
    res = await server.server.request_handlers[types.ListToolsRequest](
        types.ListToolsRequest(method="tools/list")
    )
    assert "report_error" in {t.name for t in res.root.tools}


@pytest.mark.asyncio
async def test_handler_empty_buffer_no_note_reports_nothing(server):
    out = await server._handle_report_error({})
    assert "nothing to report" in out[0].text.lower()


@pytest.mark.asyncio
async def test_handler_packages_captured_error_without_leaking_values(
    server, tmp_path, monkeypatch
):
    # Route the report file into a temp dir so the test writes nowhere real.
    monkeypatch.setenv("POE2_MCP_REPORT_DIR", str(tmp_path))
    server._error_recorder.observe(
        "inspect_spell_gem", {"spell_name": "Fireball"}, _err("Error: gem not found")
    )
    out = (await server._handle_report_error({"note": "looking up a gem"}))[0].text
    assert "Error Report Ready" in out
    assert REPORT_EMAIL in out
    assert "issues/new" in out
    # Redaction holds end-to-end: the arg value never reaches the output.
    assert "Fireball" not in out
    # The local-file floor actually wrote a report into the override dir.
    assert list(tmp_path.glob("error_report_*.json"))


@pytest.mark.asyncio
async def test_handler_clear_after_empties_buffer(server, tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_REPORT_DIR", str(tmp_path))
    server._error_recorder.observe("t", {}, _err("Error: x"))
    assert server._error_recorder.count() == 1
    await server._handle_report_error({"clear_after": True})
    assert server._error_recorder.count() == 0


@pytest.mark.asyncio
async def test_dispatcher_captures_handler_errors(server):
    # An unknown tool routes through the dispatcher's except -> "Error:" text,
    # which the wrapper should observe into the buffer.
    before = server._error_recorder.count()
    await server.handle_call_tool("this_tool_does_not_exist", {})
    assert server._error_recorder.count() == before + 1
