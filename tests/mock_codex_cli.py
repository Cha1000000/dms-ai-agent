#!/usr/bin/env python3
"""Mock codex CLI for codex_bridge tests.

Imitates `codex exec --json` stdout events (thread.started / turn.started /
item.completed / turn.completed / turn.failed / {"type":"error"}) without any
network access. Verifies the bridge's flags via quirks:

  --expect-resume:ID      fail (exit 3) unless invoked as `exec resume ID`
  --expect-model:M        fail unless -m/--model M was passed
  --expect-effort:E       fail unless -c model_reasoning_effort="E" was passed
  --fail                  emit turn.failed instead of turn.completed
  --error-item            emit an item.completed error item before the message
  --garbage               print a non-JSON line between events
  --slow                  sleep 30s after thread.started (for the cancel test)
  --stdin-echo            echo the prompt received on stdin as the message text

Event shapes are the ones captured live from codex-cli 0.166.0 (thread.started
with thread_id, item.completed with item.type/message, turn.started) plus the
turn.completed/turn.failed pair documented for exec --json.
"""
import json
import sys
import time

argv = sys.argv[1:]
quirks = set(q for q in argv if q.startswith("--"))
args = [a for a in argv if not a.startswith("--")]

state = {"model": None, "effort": None, "resume": None, "prompt": ""}

# --- flag checks (mimic codex's own argv parsing) --------------------------
i = 0
while i < len(args):
    a = args[i]
    if a in ("-m", "--model") and i + 1 < len(args):
        state["model"] = args[i + 1]
        i += 2
        continue
    if a == "-c" and i + 1 < len(args):
        kv = args[i + 1]
        if kv.startswith("model_reasoning_effort="):
            state["effort"] = kv.split("=", 1)[1].strip('"')
        i += 2
        continue
    if a == "resume" and i + 1 < len(args):
        state["resume"] = args[i + 1]
        i += 2
        continue
    if a == "-":
        state["prompt"] = sys.stdin.read()
        i += 1
        continue
    if not state["prompt"] and not args[i].startswith("-"):
        state["prompt"] = a
    i += 1

for q in quirks:
    if q.startswith("--expect-resume:"):
        want = q.split(":", 1)[1]
        if state["resume"] != want:
            sys.stderr.write("MOCK FAIL: resume %r != %r\n" % (state["resume"], want))
            sys.exit(3)
    if q.startswith("--expect-model:"):
        want = q.split(":", 1)[1]
        if state["model"] != want:
            sys.stderr.write("MOCK FAIL: model %r != %r\n" % (state["model"], want))
            sys.exit(3)
    if q.startswith("--expect-effort:"):
        want = q.split(":", 1)[1]
        if state["effort"] != want:
            sys.stderr.write("MOCK FAIL: effort %r != %r\n" % (state["effort"], want))
            sys.exit(3)

THREAD = "thread-mock-1"


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    emit({"type": "thread.started", "thread_id": THREAD})
    if "--slow" in quirks:
        time.sleep(30)
    emit({"type": "turn.started"})
    if "--garbage" in quirks:
        sys.stdout.write("2026-11-03T20:52:08Z ERROR codex_api: noise line\n")
        sys.stdout.flush()
    if "--stdin-echo" in quirks:
        text = state["prompt"]
        emit({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message",
                                                 "text": "echo:" + text}})
    else:
        if "--error-item" in quirks:
            emit({"type": "item.completed", "item": {"id": "item_1", "type": "error",
                                                     "message": "sandbox denied"}})
        emit({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message",
                                                 "text": "mock answer"}})
    if "--fail" in quirks:
        emit({"type": "turn.failed", "error": {"message": "model overloaded"}})
        return
    emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})


if __name__ == "__main__":
    main()
