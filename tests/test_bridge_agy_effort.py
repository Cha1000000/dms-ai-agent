"""TDD: Antigravity (agy acp) model+effort suffix mapping and systemPrompt in acp_bridge.py."""
import json
import os
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN, "tests"))

from test_acp_bridge import Bridge, user_msg  # noqa: E402

AVAILABLE_MODELS = [
    {"modelId": "gemini-4-argon-low", "name": "Gemini 4 Argon (Low)"},
    {"modelId": "gemini-4-argon-medium", "name": "Gemini 4 Argon (Medium)"},
    {"modelId": "gemini-4-argon-high", "name": "Gemini 4 Argon (High)"},
    {"modelId": "gemini-4-hydrogen-low", "name": "Gemini 4 Hydrogen (Low)"},
    {"modelId": "gemini-4-hydrogen-medium", "name": "Gemini 4 Hydrogen (Medium)"},
    {"modelId": "gemini-4-hydrogen-high", "name": "Gemini 4 Hydrogen (High)"},
    {"modelId": "gemini-4-hydrogen-xhigh", "name": "Gemini 4 Hydrogen (XHigh)"},
    {"modelId": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
]


def agy_mock_agent():
    """Minimal ACP agent mirroring agy 1.5.10 configOptions + availableModels."""
    trace_path = sys.argv[1]
    state = {"model": "gemini-4-argon", "thought_level": "medium", "full_model": "gemini-4-argon-medium"}

    def config_options():
        tl_opts = [
            {"value": "low", "name": "Low"},
            {"value": "medium", "name": "Medium"},
            {"value": "high", "name": "High"},
        ]
        if state["model"] == "gemini-4-hydrogen":
            tl_opts.append({"value": "xhigh", "name": "XHigh"})
        return [
            {
                "id": "model",
                "category": "model",
                "type": "select",
                "currentValue": state["model"],
                "options": [
                    {"value": "gemini-4-argon", "name": "Gemini 4 Argon"},
                    {"value": "gemini-4-hydrogen", "name": "Gemini 4 Hydrogen"},
                    {"value": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
                ],
            },
            {
                "id": "thought_level",
                "category": "thought_level",
                "type": "select",
                "currentValue": state["thought_level"],
                "options": tl_opts,
            },
        ]

    def send(obj):
        print(json.dumps(obj), flush=True)

    for line in sys.stdin:
        req = json.loads(line)
        method, rid = req.get("method"), req.get("id")
        params = req.get("params") or {}
        with open(trace_path, "a") as fh:
            fh.write(json.dumps({"method": method, "params": params}) + "\n")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": 1,
                "agentCapabilities": {"loadSession": True},
            }})
        elif method in ("session/new", "session/load"):
            if method == "session/load":
                send({"jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": params["sessionId"],
                    "update": {"sessionUpdate": "agent_message_chunk",
                               "content": {"type": "text", "text": "REPLAY_OLD"}},
                }})
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "sessionId": params.get("sessionId") or "agy-sess-1",
                "models": {"currentModelId": state["full_model"],
                           "availableModels": AVAILABLE_MODELS},
                "configOptions": config_options(),
            }})
        elif method == "session/set_model":
            mid = params.get("modelId", "")
            state["full_model"] = mid
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/set_config_option":
            key = params.get("configOptionId") or params.get("configId")
            val = params.get("value")
            if key == "thought_level" and state["model"] != "gemini-4-hydrogen" and val == "xhigh":
                send({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": -32602, "message": "xhigh not allowed"}})
                continue
            state[key] = val
            send({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": config_options()}})
        elif method == "session/prompt":
            texts = [b.get("text", "") for b in params.get("prompt", [])]
            send({"jsonrpc": "2.0", "method": "session/update", "params": {
                "sessionId": "agy-sess-1",
                "update": {"sessionUpdate": "agent_message_chunk",
                           "content": {"type": "text", "text": "|".join(texts)}},
            }})
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})


def read_trace(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_suffix_effort_uses_session_set_model_and_skips_thought_level(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gemini-4-hydrogen", "effort": "xhigh"})
        b.send(user_msg("hello"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        events = read_trace(trace)
        methods = [e["method"] for e in events]
        assert "session/set_model" in methods
        assert "session/set_config_option" not in methods
        set_model = [e for e in events if e["method"] == "session/set_model"][0]
        assert set_model["params"]["modelId"] == "gemini-4-hydrogen-xhigh"
    finally:
        b.close()


def test_auto_effort_uses_base_model_config_option(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gemini-4-hydrogen", "effort": ""})
        b.send(user_msg("hello"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        events = read_trace(trace)
        set_cfg = [e for e in events if e["method"] == "session/set_config_option"]
        assert len(set_cfg) == 1
        assert set_cfg[0]["params"]["value"] == "gemini-4-hydrogen"
        assert not any(e["method"] == "session/set_model" for e in events)
    finally:
        b.close()


def test_model_without_effort_chip_selects_exact_id(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gpt-oss-120b-medium", "effort": ""})
        b.send(user_msg("hello"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        set_model = [e for e in read_trace(trace) if e["method"] == "session/set_model"]
        assert set_model and set_model[0]["params"]["modelId"] == "gpt-oss-120b-medium"
    finally:
        b.close()


def test_unsupported_effort_is_rejected_before_prompt(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gemini-4-hydrogen", "effort": "max"})
        b.send(user_msg("hello"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is True
        methods = [e["method"] for e in read_trace(trace)]
        assert "session/prompt" not in methods
    finally:
        b.close()


def test_system_prompt_sent_once_on_first_turn_of_new_session(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gemini-4-argon", "effort": "low",
                "systemPrompt": "Be ultra concise."})
        b.send(user_msg("first"))
        res1 = b.read_until_result()
        assert res1["is_error"] is False
        assert res1["result"] == "[System instructions]\nBe ultra concise.\n\n[User message]\nfirst"

        # Second turn in the same session must NOT duplicate systemPrompt.
        b.send({"type": "config", "model": "gemini-4-argon", "effort": "low",
                "systemPrompt": "Be ultra concise.", "resumeId": res1["session_id"]})
        b.send(user_msg("second"))
        res2 = b.read_until_result()
        assert res2["is_error"] is False
        assert res2["result"] == "second"
    finally:
        b.close()


def test_system_prompt_not_injected_on_resumed_session_load(tmp_path):
    trace = tmp_path / "trace.jsonl"
    b = Bridge([str(trace)], agent=os.path.abspath(__file__))
    try:
        b.send({"type": "config", "model": "gemini-4-argon", "effort": "low",
                "resumeId": "agy-sess-1", "systemPrompt": "Be ultra concise."})
        b.send(user_msg("follow up"))
        res = b.read_until_result()
        assert res["is_error"] is False
        assert res["result"] == "follow up"
        assert "REPLAY_OLD" not in res["result"]
    finally:
        b.close()


if __name__ == "__main__":
    agy_mock_agent()
