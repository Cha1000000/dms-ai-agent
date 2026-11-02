"""TDD: the Kimi descriptor in providers.js.

providers.js is QML's `.pragma library` plain JS — node can run it once that one
line is stripped. The contract comes from the stage-4 spikes (kimi 2.4.1,
2026-11-02):

  * stream-json on stdout ONLY (stderr repeats everything — must be dropped);
  * five record shapes: meta/system.version, assistant (text and/or
    tool_calls whose arguments are a JSON *string*), tool (result text as a
    string), assistant text, meta/session.resume_hint carrying the session id;
  * no --append-system-prompt: the system prompt is prepended to the -p text;
  * effort goes in the env (KIMI_MODEL_THINKING_EFFORT), model is the full
    config key ("kimi-code/k3" — a bare "k3" is rejected), resume is
    `--session <id>`; --auto (Never Ask) CANNOT be combined with --prompt
    ("Cannot combine --prompt with --auto", caught live 2026-11-02) — print
    mode runs unattended on its own, tools never pop a dialog;
  * state.json has no model, but the wire log does (profile.bind: modelAlias +
    thinkingEffort), so the per-session model/effort restore works after all
    (perSessionRestore: true) — better than the plan's "off if state.json has
    no model", since the data lives in the other file.
"""
import json
import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_provider.js")

run = lambda fn, arg: json.loads(subprocess.run(
    ["node", NODE, fn, json.dumps(arg)], capture_output=True, text=True, check=True,
    cwd=PLUGIN,
).stdout)


def test_kimi_descriptor_shape():
    d = run("kimi_caps", {})
    assert d["id"] == "kimi"
    assert d["title"] == "Kimi Code"
    assert d["caps"] == {
        "askFirst": False,           # no permission handshake in print mode
        "cost": False,               # the CLI reports no price
        "stdinEnabled": False,       # the query is a -p argument
        "cancelViaStdin": False,
        "perSessionRestore": True,   # wire.jsonl profile.bind carries them
        "registryHistory": True,     # agent and TUI sessions look the same
    }
    assert d["canUseTool"] is False
    assert d["aliasModels"] is False
    assert d["requiresKey"] is False


def test_build_command_folds_prompt_and_effort_env():
    cmd = run("kimi_buildCommand", {
        "model": "kimi-code/k3.1-pro", "effort": "high", "confirm": False,
        "systemPrompt": "Be terse.", "prompt": "say ok", "resumeId": "",
    })
    assert "exec kimi" in cmd
    assert "--output-format stream-json" in cmd
    assert "--auto" not in cmd       # CLI: "Cannot combine --prompt with --auto"
    assert "--model 'kimi-code/k3.1-pro'" in cmd
    assert "KIMI_MODEL_THINKING_EFFORT='high'" in cmd
    assert "-p 'Be terse." in cmd       # system prompt folded into -p
    assert "say ok" in cmd
    assert "--append-system-prompt" not in cmd   # kimi has no such flag
    assert "--dangerously-skip-permissions" not in cmd
    assert "2>/dev/null" in cmd          # stderr is a duplicate of stdout


def test_build_command_resumes_by_session_id():
    cmd = run("kimi_buildCommand", {
        "model": "kimi-code/k3", "effort": "", "confirm": False,
        "systemPrompt": "sp", "prompt": "p", "resumeId": "session_abc",
    })
    assert "--session 'session_abc'" in cmd
    assert "KIMI_MODEL_THINKING_EFFORT" not in cmd   # no effort, no env


# Kimi has no --mcp-config and always reads <KIMI_CODE_HOME>/mcp.json. Measured
# 2026-11-02: a plain run starts eight helper processes from the seven servers
# in ~/.kimi-code/mcp.json; with the isolated home the delta is zero. The home
# must keep the login, config and sessions, and must not move the working dir.
def test_run_uses_an_isolated_home_without_the_users_mcp_servers():
    cmd = run("kimi_buildCommand", {
        "model": "kimi-code/k3", "effort": "", "confirm": False,
        "systemPrompt": "sp", "prompt": "p", "resumeId": "",
        "stateDir": "/home/u/.local/state/dms-agent",
    })
    assert "KIMI_CODE_HOME=\"$KIMI_HOME\"" in cmd
    assert "/home/u/.local/state/dms-agent/kimi-home" in cmd
    assert '"mcpServers": {}' in cmd
    # Login, config and sessions are linked back, not copied.
    for f in ("credentials", "oauth", "config.toml", "sessions", "session_index.jsonl"):
        assert f in cmd, f


def test_the_isolated_home_does_not_become_the_working_directory():
    cmd = run("kimi_buildCommand", {
        "model": "kimi-code/k3", "effort": "", "confirm": False,
        "systemPrompt": "sp", "prompt": "p", "resumeId": "",
        "stateDir": "/home/u/.local/state/dms-agent",
    })
    # The prep runs in a subshell: an unparenthesised cd would leave the agent
    # working in its own home instead of the project the user picked.
    assert "(cd \"$KIMI_HOME\"" in cmd
    assert cmd.count("exec kimi") == 1


def test_parse_line_drops_meta_noise():
    assert run("kimi_parseLine", '{"role":"meta","type":"system.version","version":"2.4.1"}') == []
    assert run("kimi_parseLine", "not json") == []


def test_parse_line_maps_text_and_tools_to_canonical_events():
    evs = run("kimi_parseLine", json.dumps({
        "role": "assistant", "content": "done",
        "tool_calls": [{"type": "function", "id": "tool_1",
                        "function": {"name": "Write",
                                     "arguments": '{"path":"/tmp/a","content":"hello"}'}}],
    }))
    blocks = evs[0]["message"]["content"]
    assert evs[0]["type"] == "assistant"
    assert {"type": "text", "text": "done"} in blocks
    tool = [b for b in blocks if b["type"] == "tool_use"][0]
    assert tool == {"type": "tool_use", "id": "tool_1", "name": "Write",
                    "input": {"path": "/tmp/a", "content": "hello"}}


def test_parse_line_maps_tool_result_to_a_user_event():
    evs = run("kimi_parseLine", json.dumps(
        {"role": "tool", "tool_call_id": "tool_1", "content": "Wrote 5 bytes to /tmp/a"}))
    assert evs[0]["type"] == "user"
    assert evs[0]["message"]["content"] == [
        {"type": "tool_result", "tool_use_id": "tool_1",
         "content": "Wrote 5 bytes to /tmp/a"}]


def test_parse_line_extracts_the_session_id_from_resume_hint():
    evs = run("kimi_parseLine", json.dumps({
        "role": "meta", "type": "session.resume_hint",
        "session_id": "session_3555c17f-b04d-48fb-baf4-be22832f7a25",
        "command": "kimi -r session_3555c17f", "content": "To resume..."}))
    assert evs == [{"type": "result",
                    "session_id": "session_3555c17f-b04d-48fb-baf4-be22832f7a25"}]
