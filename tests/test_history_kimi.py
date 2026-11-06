"""TDD: Kimi sessions in the history.

Kimi cannot be filtered like Claude Code (its transcripts look the same for
agent and TUI runs), so the Jarvis registry is the list (registryHistory), and
delete removes only that entry — the plan (stage 4) says the CLI has no delete
command and the files stay: "удаление — из реестра (файлы не трогаем)".

Reopening is different: restore reads the wire log the CLI keeps for every
session. Layout checked on kimi 2.4.1 (2026-11-02):

    ~/.kimi-code/sessions/wd_<slug>_<hash>/session_<id>/agents/main/wire.jsonl

The <hash> part is not derivable from the cwd, so the session dir is found by
glob. Wire records that matter:
    {"type": "profile.bind", "modelAlias": "kimi-code/k3.1-pro",
     "thinkingEffort": "high"}                          <- model/effort of the run
    {"type": "agent.message.appended", "message": {
        "message": {"role": "user", "content": [{"type": "text", ...}]}}}
    {"type": "agent.message.appended", "message": {
        "message": {"role": "assistant",
                    "content": [{"type": "think", ...}, {"type": "text", ...}]}}}
State.json carries no model, so restore takes it from profile.bind — the plan's
perSessionRestore switch stays informative: the plugin restores the model and
effort only where the provider's own record has them.
"""
import json
import os
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

WIRE = """\
{"type":"metadata","protocol_version":1}
{"type":"profile.bind","agentId":"main","modelAlias":"kimi-code/k3.1-pro","thinkingEffort":"high","systemPrompt":"You are Kimi Code CLI."}
{"type":"agent.message.appended","kind":"user","message":{"message":{"role":"user","content":[{"type":"text","text":"Reply with exactly two words: OK KIMI"}]}}}
{"type":"context.append_message","message":{"role":"system","content":"<system-reminder>noise</system-reminder>"}}
{"type":"agent.message.appended","kind":"assistant","message":{"message":{"role":"assistant","content":[{"type":"think","think":"...plan..."},{"type":"text","text":"OK KIMI"}],"toolCalls":[]}}}
"""


def write_session(home, sid, wire=WIRE):
    sdir = home / ".kimi-code" / "sessions" / "wd_demo_aabbccddeeff" / sid
    (sdir / "agents" / "main").mkdir(parents=True)
    (sdir / "agents" / "main" / "wire.jsonl").write_text(wire)
    (sdir / "state.json").write_text("{}")
    return sdir


def run_history(home, state_home, action, *args, cwd=None):
    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(state_home))
    env.pop("XDG_CACHE_HOME", None)
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"),
         "--provider", "kimi", action, *args],
        env=env, capture_output=True, text=True, cwd=cwd or str(home),
    )


def test_restore_reads_the_wire_log_messages(tmp_path):
    home = tmp_path / "home"
    write_session(home, "session_demo-1")
    out = run_history(home, tmp_path / "state", "restore", "session_demo-1")
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    roles = [(m["role"], m["content"]) for m in data["messages"]]
    assert roles == [
        ("user", "Reply with exactly two words: OK KIMI"),
        ("assistant", "OK KIMI"),  # the "think" part is not chat content
    ]


def test_restore_reports_the_model_and_effort_the_run_used(tmp_path):
    home = tmp_path / "home"
    write_session(home, "session_demo-1")
    data = json.loads(run_history(home, tmp_path / "state", "restore", "session_demo-1").stdout)
    assert data["model"] == "kimi-code/k3.1-pro"
    assert data["effort"] == "high"


def test_restore_of_an_unknown_session_is_empty(tmp_path):
    home = tmp_path / "home"
    (home / ".kimi-code" / "sessions").mkdir(parents=True)
    data = json.loads(run_history(home, tmp_path / "state", "restore", "session_nope").stdout)
    # originDir: restore now reports the directory it looked from (context
    # transfer of a session from another directory needs the origin — step 5).
    assert data == {"messages": [], "model": "", "effort": "",
                    "originDir": str(home)}


def test_delete_removes_the_registry_entry_and_keeps_the_files(tmp_path):
    home = tmp_path / "home"
    sdir = write_session(home, "session_demo-1")
    state_home = tmp_path / "state"
    reg = run_history(home, state_home, "register", "session_demo-1", "demo")
    assert json.loads(reg.stdout) == {"registered": 1}
    out = run_history(home, state_home, "delete", "session_demo-1")
    assert json.loads(out.stdout) == {"deleted": 1}
    # The wire log is untouched: kimi has no delete command (plan stage 4).
    assert (sdir / "agents" / "main" / "wire.jsonl").is_file()
    assert json.loads(run_history(home, state_home, "list").stdout) == []
    # ...but the session can still be reopened, same as /resume in the CLI.
    data = json.loads(run_history(home, tmp_path / "state", "restore", "session_demo-1").stdout)
    assert data["messages"][0]["role"] == "user"


def test_delete_all_keeps_the_files_too(tmp_path):
    home = tmp_path / "home"
    sdir = write_session(home, "session_demo-1")
    state_home = tmp_path / "state"
    run_history(home, state_home, "register", "session_demo-1", "demo")
    out = run_history(home, state_home, "delete-all")
    assert json.loads(out.stdout) == {"deleted": 1}
    assert (sdir / "agents" / "main" / "wire.jsonl").is_file()


def test_list_shows_registered_sessions_of_this_directory(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    state_home = tmp_path / "state"
    run_history(home, state_home, "register", "session_demo-1", "demo title")
    rows = json.loads(run_history(home, state_home, "list").stdout)
    assert [(r["id"], r["title"]) for r in rows] == [("session_demo-1", "demo title")]
