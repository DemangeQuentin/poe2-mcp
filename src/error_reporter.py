"""
Opt-in error reporting for the PoE2 MCP (`report_error` tool).

Design constraints (deliberate):
  * NO network egress and NO shipped secret. This module never sends anything.
    It PACKAGES a redacted report and hands the user copy-ready channels
    (a local file, a prefilled `mailto:`, a prefilled GitHub issue URL). The
    user chooses whether/where to submit, so consent is inherent and there is
    nothing to abuse.
  * Privacy by construction. `ErrorRecorder` stores only argument *keys*, never
    argument *values* — so character names, pasted PoB codes, URLs, etc. never
    enter the buffer in the first place. Messages are length-capped.

An MCP server can only observe errors raised inside its own tool handlers (it
cannot see the wider conversation), which is exactly the high-signal data worth
reporting. The dispatcher scans each tool result for the handlers' `Error:`
convention and records it here.
"""

from __future__ import annotations

import platform
import sys
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import quote

# Where a manual report is addressed. A dedicated alias so a spam wave can be
# filtered/killed without touching a working identity. Public by nature (it
# ships in the source) — that is an accepted cost of the no-infra mailto path.
REPORT_EMAIL = "poe2-mcp@portertech.llc"
GITHUB_REPO = "HivemindOverlord/poe2-mcp"
ISSUE_LABEL = "mcp-error-report"

# Keep the buffer small — this is "what went wrong recently", not an audit log.
_MAX_ERRORS = 25
_MESSAGE_CAP = 600

# URL length ceilings so prefilled links stay within client/browser limits.
_MAILTO_BODY_CAP = 1800
_GITHUB_BODY_CAP = 6000


class ErrorRecorder:
    """Bounded ring buffer of redacted handler-error records."""

    def __init__(self, maxlen: int = _MAX_ERRORS) -> None:
        self._buf: Deque[Dict[str, Any]] = deque(maxlen=maxlen)

    def observe(self, tool: str, arguments: Optional[dict], result: Any) -> None:
        """Record an error if `result` carries a handler `Error:` response.

        Only argument keys are stored, never values (privacy). Any failure here
        is swallowed by the caller — telemetry must never break a tool call.
        """
        for item in result or []:
            text = getattr(item, "text", "") or ""
            if text.startswith("Error:"):
                self._buf.append(
                    {
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "tool": tool,
                        "arg_keys": sorted((arguments or {}).keys()),
                        "message": text[:_MESSAGE_CAP],
                    }
                )
                return

    def record_message(self, tool: str, message: str) -> None:
        """Directly record a message (e.g. a propagated exception)."""
        self._buf.append(
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "tool": tool,
                "arg_keys": [],
                "message": (message or "")[:_MESSAGE_CAP],
            }
        )

    def recent(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        items = list(self._buf)
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def count(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()


def _env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    if extra:
        env.update({k: v for k, v in extra.items() if v})
    return env


def build_report(
    errors: List[Dict[str, Any]],
    note: str = "",
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assemble a redacted report dict from captured errors + an optional note."""
    return {
        "generated": datetime.utcnow().isoformat() + "Z",
        "env": _env(extra_env),
        "user_note": (note or "").strip(),
        "error_count": len(errors),
        "errors": errors,
    }


def report_to_text(report: Dict[str, Any], markdown: bool = False) -> str:
    """Render a report as a human-readable block (plain text or Markdown)."""
    env = report.get("env", {})
    lines: List[str] = []
    lines.append("PoE2 MCP error report")
    lines.append(f"Generated: {report.get('generated', '?')}")
    lines.append(
        "Env: python "
        + env.get("python", "?")
        + " | "
        + env.get("platform", "?")
        + (f" | data {env['data_version']}" if env.get("data_version") else "")
    )
    lines.append(f"Errors captured: {report.get('error_count', 0)}")
    lines.append("")
    lines.append("User note:")
    lines.append(report.get("user_note") or "(none)")
    lines.append("")
    lines.append("Errors:")
    if not report.get("errors"):
        lines.append("(none captured)")
    for i, err in enumerate(report.get("errors", []), 1):
        keys = ", ".join(err.get("arg_keys", [])) or "(none)"
        lines.append(f"[{i}] {err.get('ts', '?')}  tool={err.get('tool', '?')}")
        lines.append(f"    arg keys: {keys}")
        lines.append(f"    {err.get('message', '')}")
    body = "\n".join(lines)
    if markdown:
        note = report.get("user_note") or "_(none)_"
        header = (
            "Thanks for reporting a PoE2 MCP problem. The details below are "
            "auto-generated and contain no argument values (only key names).\n\n"
            f"**What were you doing?** {note}\n\n"
        )
        return header + "```\n" + body + "\n```\n"
    return body


def _title(report: Dict[str, Any]) -> str:
    n = report.get("error_count", 0)
    first = ""
    if report.get("errors"):
        first = f" in {report['errors'][-1].get('tool', '')}".rstrip()
    return f"MCP error report ({n} error{'s' if n != 1 else ''}{first})"


def mailto_link(report: Dict[str, Any], email: str = REPORT_EMAIL) -> str:
    body = report_to_text(report, markdown=False)
    if len(body) > _MAILTO_BODY_CAP:
        body = body[:_MAILTO_BODY_CAP] + "\n...(truncated — see the saved report file)"
    return f"mailto:{email}" f"?subject={quote(_title(report))}" f"&body={quote(body)}"


def github_issue_link(report: Dict[str, Any], repo: str = GITHUB_REPO) -> str:
    body = report_to_text(report, markdown=True)
    if len(body) > _GITHUB_BODY_CAP:
        body = body[:_GITHUB_BODY_CAP] + "\n...(truncated — attach the saved report file)\n```"
    return (
        f"https://github.com/{repo}/issues/new"
        f"?labels={quote(ISSUE_LABEL)}"
        f"&title={quote(_title(report))}"
        f"&body={quote(body)}"
    )
