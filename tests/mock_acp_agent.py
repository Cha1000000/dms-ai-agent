#!/usr/bin/env python3
"""Mock ACP agent for the acp_bridge tests.

Speaks enough JSON-RPC 2.0 over stdin/stdout to exercise the bridge:
initialize, session/new, session/load, session/set_config_option,
session/prompt, session/request_permission, session/update chunks and
session/cancel. Configurable quirks per test via argv flags.
"""
import json
import sys
import threading

quirks = set(sys.argv[1:])

IN = sys.stdin
OUT = sys.stdout


def send(obj):
    OUT.write(json.dumps(obj) + "\n")
    OUT.flush()


def reply(id_, result):
    send({"jsonrpc": "2.0", "id": id_, "result": result})


def error(id_, code, message):
    send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


SESSION = "sess-123"
state = {"id": 100, "session": None, "prompting": False, "config": {}, "loaded": False}


def _die(msg):
    sys.stderr.write("MOCK FAIL: " + msg + "\n")
    sys.stderr.flush()
    sys.exit(3)


def next_id():
    state["id"] += 1
    return state["id"]


def handle_request(req):
    method = req.get("method", "")
    id_ = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        # The same schema check a real agent does (gemini --acp rejects
        # clientCapabilities.fs as a boolean: the field is an object).
        caps = params.get("clientCapabilities")
        if not isinstance(caps, dict):
            _die("clientCapabilities must be an object, got %r" % (caps,))
        fs = caps.get("fs")
        if fs is not None and not isinstance(fs, dict):
            _die("clientCapabilities.fs must be an object, got %r" % (fs,))
        reply(id_, {"protocolVersion": 1, "agentCapabilities": {
            "loadSession": "no-load" not in quirks,
        }, "authMethod": "none" if "--needs-auth" in quirks else None})

    elif method == "session/new":
        if "needs-auth" in quirks and not params.get("_authorized"):
            error(id_, -32000, "auth required")
            return
        state["session"] = SESSION
        if "models-form" in quirks:
            # The second ACP config shape (gemini-cli 0.66): the model list
            # comes as models.availableModels, not as configOptions, and the
            # model is selected with session/set_model.
            reply(id_, {"sessionId": SESSION,
                        "models": {"availableModels": [
                            {"modelId": "m-fast", "name": "Fast"},
                            {"modelId": "m-big", "name": "Big"},
                        ], "currentModelId": state["config"].get("model", "m-fast")},
                        "modes": {"availableModes": [
                            {"id": "default", "name": "Default"},
                        ], "currentModeId": "default"}})
            return
        reply(id_, {"sessionId": SESSION, "configOptions": [
            {"id": "model", "name": "Model", "category": "model", "type": "select",
             "currentValue": "m-fast", "options": [
                 {"value": "m-fast", "name": "Fast"},
                 {"value": "m-big", "name": "Big"}]},
            {"id": "effort", "name": "Effort", "category": "effort", "type": "select",
             "currentValue": "e-med", "options": [
                 {"value": "e-low", "name": "Low"},
                 {"value": "e-med", "name": "Medium"}]},
        ]})

    elif method == "session/load":
        if "--no-load" in quirks:
            error(id_, -32601, "Method not found")
            return
        state["session"] = params.get("sessionId", SESSION)
        state["loaded"] = True
        reply(id_, {})

    elif method == "session/set_config_option":
        state["config"][params.get("configOptionId", params.get("id", "?"))] = params.get("value")
        reply(id_, {"configOptions": [
            {"id": "model", "name": "Model", "category": "model", "type": "select",
             "currentValue": state["config"].get("model", "m-fast"), "options": [
                 {"value": "m-fast", "name": "Fast"},
                 {"value": "m-big", "name": "Big"}]},
            {"id": "effort", "name": "Effort", "category": "effort", "type": "select",
             "currentValue": state["config"].get("effort", "e-med"), "options": [
                 {"value": "e-low", "name": "Low"},
                 {"value": "e-med", "name": "Medium"}]},
        ]})

    elif method == "session/set_model":
        state["config"]["model"] = params.get("modelId")
        reply(id_, {})

    elif method == "session/set_mode":
        state["config"]["mode"] = params.get("modeId")
        reply(id_, {})

    elif method == "session/prompt":
        state["prompt_id"] = id_
        # The expect-* quirks verify what the bridge did BEFORE prompting.
        for spec in [q for q in quirks if q.startswith("--expect-config")]:
            pass
        if "--expect-load" in quirks and not state["loaded"]:
            _die("bridge never sent session/load")
        for q in quirks:
            if q.startswith("--expect-config:"):
                for pair in q.split(":", 1)[1].split(","):
                    key, want = pair.split("=", 1)
                    got = state["config"].get(key)
                    if got != want:
                        _die("config %s: bridge sent %r, expected %r" % (key, got, want))
        state["prompting"] = True
        sid = params.get("sessionId", SESSION)
        # The ACP schema names the field "prompt" (gemini --acp rejects
        # "content": "expected 'array', received undefined"). A client that
        # sends only "content" is broken and must fail here.
        if "prompt" not in params:
            _die("session/prompt without a prompt array")
        content = params.get("prompt", [])
        text = ""
        for c in content:
            if c.get("type") == "text":
                text += c.get("text", "")
        # Echo the text back, then a final message, then done.
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk",
                                          "content": {"type": "text", "text": "echo:" + text}}}})
        if "--ask" in quirks:
            rid = next_id()
            send({"jsonrpc": "2.0", "id": rid, "method": "session/request_permission",
                  "params": {"sessionId": sid, "options": [
                      {"optionId": "opt-allow", "name": "Allow", "kind": "allow_once"},
                      {"optionId": "opt-reject", "name": "Reject", "kind": "reject_once"},
                  ], "toolCall": {"toolCallId": "t1", "title": "run something"}}})
            # Stop here: the test drives the next step.
            state["prompting"] = "waiting-permission"
            return
        if "--never-done" in quirks:
            state["prompting"] = False
            return  # no session/update done, no stopReason — hangs unless cancelled
        send({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "update": {"sessionUpdate": "done"}}})
        state["prompting"] = False
        reply(id_, {"stopReason": "end_turn"})

    elif method == "fs/read_text_file" or method == "fs/write_text_file":
        # The mock agent grants fs access only via permission; a real agent
        # would run the tool here. Accept silently.
        reply(id_, {"content": ""})

    elif method == "session/cancel":
        state["prompting"] = False
        # After a cancel the pending prompt must return; the spec lets the
        # agent end it either way. The mock replies with stopReason cancelled
        # so the bridge can test both shapes.
        if "--cancel-replies" in quirks:
            reply(id_, {"stopReason": "cancelled"})

    else:
        if id_ is not None:
            error(id_, -32601, "Method not found: %s" % method)


def finish_prompt_after_permission(resp):
    """The permission answer arrived: close out the prompt that asked."""
    outcome = ((resp or {}).get("result") or {}).get("outcome") or {}
    allow = outcome.get("optionId") == "opt-allow"
    sid = state.get("session") or SESSION
    send({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk",
                                      "content": {"type": "text", "text": "allowed" if allow else "rejected"}}}})
    send({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": sid, "update": {"sessionUpdate": "done"}}})
    reply(state.get("prompt_id"), {"stopReason": "end_turn" if allow else "refusal"})
    state["prompting"] = False


def main():
    for line in IN:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        # A response (not a request): the only ones are permission answers.
        if "id" in req and "method" not in req:
            finish_prompt_after_permission(req)
            continue
        handle_request(req)


if __name__ == "__main__":
    main()
