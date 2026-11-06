"""Contract tests with a local ACP agent; no network or model calls."""
import json
import os
import sys

import pytest

from test_acp_bridge import Bridge, user_msg


def agent():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok"
    selections = {"engine": "fast", "reasoning": "medium"}
    if scenario == "legacy":
        selections = {"model": "m-fast", "effort": "e-med"}

    def options():
        if scenario == "legacy":
            return [
                {"id": "model", "category": "model", "type": "select", "currentValue": selections["model"], "options": [{"value": "m-fast"}, {"value": "m-big"}]},
                {"id": "effort", "category": "effort", "type": "select", "currentValue": selections["effort"], "options": [{"value": "e-low"}, {"value": "e-med"}]},
            ]
        return [
            {"id": "engine", "category": "model", "type": "select", "currentValue": selections["engine"], "options": [{"value": "fast"}, {"value": "large"}]},
            {"id": "reasoning", "category": "thought_level", "type": "select", "currentValue": selections["reasoning"], "options": [{"group": "levels", "name": "Levels", "options": [{"value": "low"}, {"value": "medium"}]}]},
        ]

    def send(message):
        print(json.dumps(message), flush=True)

    for line in sys.stdin:
        req = json.loads(line)
        method, rid = req.get("method"), req.get("id")
        if len(sys.argv) > 2:
            with open(sys.argv[2], "a") as trace:
                trace.write(str(method) + "\n")
        params = req.get("params", {})
        result = {}
        if method == "initialize":
            result = {"protocolVersion": 1}
        elif method in ("session/new", "session/load"):
            result = {"configOptions": [] if scenario == "missing" else options()}
            if method == "session/new":
                result["sessionId"] = "session-1"
        elif method == "session/set_config_option":
            if scenario == "reject":
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unsupported"}})
                continue
            key = params.get("configOptionId") or params.get("configId")
            if key not in selections:
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid ID"}})
                continue
            if scenario != "unconfirmed":
                selections[key] = params["value"]
            result = {"configOptions": [] if scenario == "no-confirmation" else options()}
        elif method == "session/prompt":
            if scenario == "context":
                texts = [item.get("text") for item in params.get("prompt", [])]
                if selections["engine"] != "large" or texts != ["User: first", "Assistant: answer", "second"]:
                    send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "context or configuration missing"}})
                    continue
            if scenario in ("ok", "legacy"):
                expected = {"engine": "large", "reasoning": "low"} if scenario == "ok" else {"model": "m-big", "effort": "e-low"}
                if selections != expected:
                    send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "settings not applied"}})
                    continue
            if scenario in ("missing", "reject", "unconfirmed", "no-confirmation", "unoffered"):
                send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "PROMPT WAS SENT"}})
                continue
            for kind, content in [("agent_message_chunk", {"type": "text", "text": "Hello "}),
                                  ("agent_thought_chunk", {"type": "text", "text": "secret"}),
                                  ("agent_message_chunk", {"type": "text", "text": "world"})]:
                send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "session-1", "update": {"sessionUpdate": kind, "content": content}}})
            result = {"stopReason": "end_turn"}
        else:
            continue
        send({"jsonrpc": "2.0", "id": rid, "result": result})


def start(scenario="ok"):
    return Bridge([scenario], agent=os.path.abspath(__file__))


@pytest.mark.parametrize("resume", [False, True])
def test_real_config_ids_values_and_stream_result(resume):
    bridge = start()
    try:
        config = {"type": "config", "model": "large", "effort": "low"}
        if resume:
            config["resumeId"] = "session-1"
        bridge.send(config)
        for text in ("first", "second"):
            bridge.send(user_msg(text))
            result = bridge.read_until_result()
            assert result["is_error"] is False, result
            assert result["result"] == "Hello world"
    finally:
        bridge.close()


def test_configured_turn_preserves_context(tmp_path):
    context = tmp_path / "context.jsonl"
    context.write_text(json.dumps({"role": "user", "content": "first"}) + "\n" +
                       json.dumps({"role": "assistant", "content": "answer"}) + "\n")
    bridge = start("context")
    try:
        bridge.send({"type": "config", "model": "large", "contextFile": str(context)})
        bridge.send(user_msg("second"))
        result = bridge.read_until_result()
        assert result["is_error"] is False, result
        assert result["result"] == "Hello world"
    finally:
        bridge.close()


@pytest.mark.parametrize("scenario,model,reason", [
    ("missing", "large", "unavailable"),
    ("unoffered", "unknown", "not offered"),
    ("reject", "large", "rejected"),
    ("unconfirmed", "large", "not confirmed"),
    ("no-confirmation", "large", "not confirmed"),
])
def test_config_failure_stops_prompt(scenario, model, reason, tmp_path):
    trace = tmp_path / "methods"
    bridge = Bridge([scenario, str(trace)], agent=os.path.abspath(__file__))
    try:
        bridge.send({"type": "config", "model": model})
        bridge.send(user_msg("do not send"))
        result = bridge.read_until_result()
        assert result["is_error"] is True
        assert any(reason in error for error in result["errors"]), result
        assert not any(event.get("type") == "assistant" for event in bridge.lines)
    finally:
        bridge.close()
    assert "session/prompt" not in trace.read_text().splitlines()


if __name__ == "__main__":
    agent()
