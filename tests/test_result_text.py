"""TDD: what the chat shows when the CLI ends a run without any answer text.

Caught live 2026-11-02 on the stand and in the real chat: several providers
answered "(done)". That string was not a model's reply — AgentService printed
it whenever the "result" event carried no text, and the CLI puts the reason of
such a run in `errors[]` instead of `result`:

    {"type":"result","subtype":"error_during_execution","is_error":true,
     "errors":["No conversation found with session ID: …"]}   # no "result" key

Contract: the chat shows that reason. "(done)" may only stand for a run that
really finished with nothing to say (a successful result with empty text), so
a user can tell "the agent had nothing to add" from "the run failed".
"""
import json
import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_provider.js")

def run(fn, arg, last_text=""):
    return json.loads(subprocess.run(
        ["node", NODE, fn, json.dumps({"event": arg, "lastText": last_text})],
        capture_output=True, text=True, check=True, cwd=PLUGIN,
    ).stdout)

FAILED = {"type": "result", "subtype": "error_during_execution", "is_error": True,
          "errors": ["No conversation found with session ID: x"], "num_turns": 0}
EMPTY = {"type": "result", "subtype": "success", "is_error": False, "result": ""}
WITH_TEXT = {"type": "result", "subtype": "success", "is_error": False, "result": "OK"}


def test_a_failed_run_reports_the_reason_not_done():
    text = run("result_text", FAILED)
    assert "(done)" != text
    assert "No conversation found" in text


def test_a_failed_run_without_errors_still_says_it_failed():
    ev = {"type": "result", "subtype": "error_during_execution", "is_error": True}
    text = run("result_text", ev)
    assert text.strip() != ""
    assert "(done)" != text


def test_a_successful_but_empty_run_is_not_an_error():
    assert run("result_text", EMPTY) == ""


def test_normal_text_passes_through():
    assert run("result_text", WITH_TEXT) == "OK"


def test_result_text_prefers_the_last_streamed_text():
    # A provider that streams text but ends with an empty result still has an answer.
    assert run("result_text", EMPTY, "streamed answer") == "streamed answer"
    # The reason of a failed run wins over stale streamed text.
    assert "No conversation found" in run("result_text", FAILED, "streamed answer")
