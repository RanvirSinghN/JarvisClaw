"""
OpenClaw adapter for the Jarvis project.

This module is the bridge between the Python app and OpenClaw.
The rest of the app should call ask_openclaw(message) and should not need to know
anything else about OpenClaw's APIs or config.

Current backend:
- cli: uses `openclaw agent ... --json`
"""

import json
import shutil
import subprocess
import config

# -----------------------------
# CLI backend config
# -----------------------------

# `openclaw agent --session-id` expects the internal UUID session id,
# not the human-readable session key shown by /status.
JARVIS_SESSION_ID = getattr(
    config,
    "JARVIS_SESSION_ID",
    "68ef44a5-6577-438c-9820-0b13370e0e07",
)

# Command name used to call OpenClaw from the terminal.
OPENCLAW_COMMAND = "openclaw"


DEFAULT_TIMEOUT_SECONDS = getattr(config, "DEFAULT_TIMEOUT_SECONDS", 120)
DEBUG = getattr(config, "DEBUG", False)


def ask_openclaw(message: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """
    CLI implementation.

    Wraps:
    openclaw agent --session-id <uuid> --message <text> --json --timeout <seconds>
    """
    if not shutil.which(OPENCLAW_COMMAND):
        raise RuntimeError(
            "OpenClaw CLI not found. Check that `openclaw` is installed and available on your PATH."
        )

    command = [
        OPENCLAW_COMMAND,
        "agent",
        "--session-id",
        JARVIS_SESSION_ID,
        "--message",
        message,
        "--json",
        "--timeout",
        str(timeout_seconds),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OpenClaw timed out after {timeout_seconds} seconds. "
            "The gateway may be busy, offline, or the model may be taking too long."
        ) from exc

    if DEBUG:
        print("\n[debug] OpenClaw stdout:")
        print(result.stdout)
        print("\n[debug] OpenClaw stderr:")
        print(result.stderr)

    if result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip() or "OpenClaw command failed"
        raise RuntimeError(f"OpenClaw CLI returned an error: {error_message}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        preview = result.stdout[:500].strip()
        raise RuntimeError(
            "OpenClaw did not return valid JSON. "
            f"Output preview: {preview or '<empty>'}"
        ) from exc

    return _extract_reply_from_openclaw_data(data)


def _extract_reply_from_openclaw_data(data: dict) -> str:
    """Extract assistant text from the CLI JSON output."""
    if data.get("status") != "ok":
        raise RuntimeError(
            f"OpenClaw returned non-ok status: {data.get('status')}. "
            f"Summary: {data.get('summary')}"
        )

    reply = (
        data.get("result", {})
        .get("meta", {})
        .get("finalAssistantVisibleText")
    )

    if not reply:
        payloads = data.get("result", {}).get("payloads", [])
        if payloads:
            reply = payloads[0].get("text")

    if not reply:
        raise RuntimeError(
            "Could not find assistant reply in OpenClaw JSON output. "
            "Set DEBUG = True in openclaw_adapter.py to inspect the raw response."
        )

    return reply
