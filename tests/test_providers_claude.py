"""TDD: how the Claude-family descriptors are launched, and how Cancel stops them.

The Cancel button writes a control_request/interrupt into the CLI's stdin. That
only works when the run keeps a live pipe: a prompt passed as a heredoc closes
stdin before the CLI even starts, and the interrupt never arrives. SIGTERM
gives no result event at all, so the chat would show "agent exited without a
response" instead of "Cancelled".

Contract:
  - the prompt goes through stdin, not through argv or a heredoc
  - --input-format stream-json is set for both providers
  - claude and cvc can cancel via stdin (caps.cancelViaStdin)
  - the user message format is the stream-json one
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(PLUGIN, "tests", "run_provider.js")


def _run(fn, arg=None):
    out = subprocess.run(["node", HARNESS, fn, json.dumps(arg or {})],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _build(fn, **opts):
    opts.setdefault("model", "claude-opus-5-5")
    opts.setdefault("effort", "")
    opts.setdefault("confirm", False)
    opts.setdefault("systemPrompt", "sys")
    opts.setdefault("prompt", "PROMPT-TEXT")
    opts.setdefault("resumeId", "")
    return _run(fn, opts)


def test_the_prompt_is_not_an_argument():
    # A prompt in argv is visible in /proc/<pid>/cmdline, and a heredoc closes
    # stdin — the channel the interrupt needs.
    cmd = _build("claude_buildCommand")
    assert "PROMPT-TEXT" not in cmd, cmd
    assert "<<<" not in cmd, cmd


def test_the_run_reads_the_prompt_from_stdin():
    cmd = _build("claude_buildCommand")
    assert "--input-format stream-json" in cmd, cmd


def test_stdin_is_used_in_both_permission_modes():
    for confirm in (True, False):
        cmd = _build("claude_buildCommand", confirm=confirm)
        assert "--input-format stream-json" in cmd, cmd
        assert "PROMPT-TEXT" not in cmd, cmd


def test_cvc_uses_the_same_stdin_run():
    cmd = _build("cvc_buildCommand")
    assert "--input-format stream-json" in cmd, cmd
    assert "PROMPT-TEXT" not in cmd, cmd


def test_claude_and_cvc_cancel_through_stdin():
    for fn in ("claude_caps", "cvc_caps"):
        caps = _run(fn)["caps"]
        assert caps["cancelViaStdin"] is True, fn
        assert caps["stdinEnabled"] is True, fn


def test_the_user_message_is_the_stream_json_one():
    caps = _run("claude_caps")
    msg = caps["stdinUserFormat"]
    assert msg["type"] == "user", msg
    assert msg["message"]["role"] == "user", msg
    assert msg["message"]["content"] == "hi", msg


def test_the_permission_dialog_is_still_a_stdio_tool():
    cmd = _build("claude_buildCommand", confirm=True)
    assert "--permission-prompt-tool stdio" in cmd, cmd
    # The unattended mode still skips permissions.
    auto = _build("claude_buildCommand", confirm=False)
    assert "--dangerously-skip-permissions" in auto, auto
