"""TDD: history.py for a registry-backed provider (Qoder).

Qoder transcripts live in ~/.qoder/projects/<slug-of-cwd>/*.jsonl and look the
same for headless and interactive runs, so the plugin cannot scan them for
"sessions this chat started" — the Jarvis session registry is that record
(sessions_registry.py). Contract from tools/plans/jarvis-multi-provider.md,
stage 3: history-адаптер qoder (свои типы записей), restore из runtime-config,
переименование/удаление.

Facts the fixtures mirror (checked on qodercli 1.1.81, 2026-11-02):
  - user/assistant records are claude-shaped (message.content blocks);
  - the model is stamped "qfmodel" (an internal alias), effort lives in
    runtime-config.reasoningEffort and is null unless it differs from the
    default (high);
  - --resume searches only the current project, so the panel may show only
    sessions of its own working directory.
"""
import json
import os
import re
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_history(home, cwd, *args):
    env = dict(os.environ, HOME=str(home))
    env.pop("XDG_STATE_HOME", None)
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )


def make_qoder_session(home, cwd, sid, prompt="Привет", reply="Готово",
                       effort="low", model="qfmodel"):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = home / ".qoder" / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "workspace-directories", "directories": [str(cwd)], "sessionId": sid},
        {"type": "runtime-config", "sessionId": sid, "model": model, "reasoningEffort": effort},
        {"type": "user", "sessionId": sid,
         "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}},
        {"type": "attachment", "sessionId": sid, "attachment": {}},
        {"type": "assistant", "sessionId": sid,
         "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "думаю"}]}},
        {"type": "assistant", "sessionId": sid,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "t1", "name": "Write", "input": {}}]}},
        {"type": "user", "sessionId": sid,
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "sessionId": sid,
         "message": {"role": "assistant", "content": [{"type": "text", "text": reply}]}},
        {"type": "last-prompt", "sessionId": sid, "lastPrompt": prompt},
    ]
    path = proj / (sid + ".jsonl")
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
    (proj / sid).mkdir(exist_ok=True)  # the sidecar dir qoder keeps per session
    return path


def make_claude_session(home, cwd, sid):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = home / ".claude" / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / (sid + ".jsonl")
    path.write_text(
        '{"type":"user","message":{"content":"Hello there"}}\n'
        '{"type":"assistant","requestedModel":"claude-sonnet-5-5","effort":"high",'
        '"message":{"content":[{"type":"text","text":"Hi!"}]}}\n'
    )
    return path


def registry_data(home):
    path = home / ".local" / "state" / "dms-agent" / "sessions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def test_register_creates_a_registry_entry(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    out = run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")
    assert json.loads(out.stdout) == {"registered": 1}
    entry = registry_data(home)["qoder"][sid]
    assert entry["title"] == "Привет"
    assert entry["workDir"] == str(cwd)


def test_register_keeps_the_title_of_a_renamed_session(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Первый")
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Второй")
    assert registry_data(home)["qoder"][sid]["title"] == "Первый"


def test_list_shows_registered_sessions_with_their_titles(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    run_history(home, cwd, "--provider", "qoder", "register", "s1", "Первая")
    run_history(home, cwd, "--provider", "qoder", "register", "s2", "Вторая")
    out = run_history(home, cwd, "--provider", "qoder", "list")
    rows = json.loads(out.stdout)
    assert {r["id"]: r["title"] for r in rows} == {"s1": "Первая", "s2": "Вторая"}
    assert all(r["name"] == r["title"] and r["date"] > 0 for r in rows)


def test_list_hides_sessions_of_another_working_directory(tmp_path):
    home = tmp_path / "home"
    here, there = tmp_path / "here", tmp_path / "there"
    here.mkdir()
    there.mkdir()
    run_history(home, here, "--provider", "qoder", "register", "s-here", "Здесь")
    assert json.loads(run_history(home, there, "--provider", "qoder", "list").stdout) == []
    rows = json.loads(run_history(home, here, "--provider", "qoder", "list").stdout)
    assert [r["id"] for r in rows] == ["s-here"]


def test_restore_reads_text_messages_and_skips_tool_records(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    make_qoder_session(home, cwd, sid, prompt="Сделай файл", reply="Сделал")
    out = run_history(home, cwd, "--provider", "qoder", "restore", sid)
    assert json.loads(out.stdout)["messages"] == [
        {"role": "user", "content": "Сделай файл"},
        {"role": "assistant", "content": "Сделал"},
    ]


def test_restore_reports_model_and_effort_from_runtime_config(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    # "qfmodel" is what qoder really writes: an internal alias the model picker
    # will not match, and applySessionModel then leaves the choice alone.
    make_qoder_session(home, cwd, sid, effort="xhigh", model="qfmodel")
    out = run_history(home, cwd, "--provider", "qoder", "restore", sid)
    restored = json.loads(out.stdout)
    assert restored["model"] == "qfmodel"
    assert restored["effort"] == "xhigh"


def test_restore_of_a_missing_session_is_empty(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    out = run_history(home, cwd, "--provider", "qoder", "restore", "ghost")
    # originDir: restore now reports where it looked (context transfer of a
    # session from another directory needs the origin — step 5 of the plan).
    assert json.loads(out.stdout) == {"messages": [], "model": "", "effort": "",
                                      "originDir": str(cwd)}


def test_restore_of_a_claude_session_still_works(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    make_claude_session(home, cwd, sid)
    out = run_history(home, cwd, "--provider", "claude", "restore", sid)
    restored = json.loads(out.stdout)
    assert restored["messages"] == [
        {"role": "user", "content": "Hello there"},
        {"role": "assistant", "content": "Hi!"},
    ]
    assert restored["model"] == "claude-sonnet-5-5"
    assert restored["effort"] == "high"


def test_restore_finds_a_session_registered_in_another_directory(tmp_path):
    # The panel lists --all-dirs; a session registered elsewhere must open
    # from here: text reads fine, but originDir says where it lives, so the
    # chat knows a native --resume cannot find it back (context transfer).
    home, cwd, other = tmp_path / "home", tmp_path / "work", tmp_path / "other"
    cwd.mkdir(parents=True)
    other.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    make_claude_session(home, other, sid)
    reg = home / ".local" / "state" / "dms-agent" / "sessions.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"claude": {sid: {
        "title": "чужой", "workDir": str(other), "ts": 1.0}}}))
    restored = json.loads(run_history(home, cwd, "--provider", "claude", "restore", sid).stdout)
    assert restored["messages"] == [
        {"role": "user", "content": "Hello there"},
        {"role": "assistant", "content": "Hi!"},
    ]
    assert restored["originDir"] == str(other)


def test_delete_removes_transcript_sidecar_and_registry_entry(tmp_path):
    """Superseded 2026-11-02: the session is deleted by qodercli itself.

    Deleting the files by hand left the CLI's own session index pointing at a
    session that was gone, and the next --resume found a broken one. The CLI
    removes the transcript and the sidecar directory together — see
    test_history_qoder_delete.py for the contract with the CLI.
    """
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    path = make_qoder_session(home, cwd, sid)
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")
    out = run_history(home, cwd, "--provider", "qoder", "delete", sid)
    # Without a qodercli that knows this session the delete cannot happen.
    assert json.loads(out.stdout) == {"deleted": 0, "removed": 0}
    assert path.exists()
    # The registry is the ONLY listing source for Qoder, so an entry whose
    # session could not be removed must stay: hiding it would lose a live
    # session from history without deleting anything (plan: the deletion
    # error is not hidden).
    assert sid in registry_data(home).get("qoder", {})


def test_delete_refuses_a_session_the_registry_does_not_know(tmp_path):
    """An interactive Qoder session looks exactly like ours in the transcript
    store — only the registry knows which sessions this chat owns."""
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    path = make_qoder_session(home, cwd, sid)
    out = run_history(home, cwd, "--provider", "qoder", "delete", sid)
    assert json.loads(out.stdout) == {"deleted": 0, "removed": 0}
    assert path.exists()


def test_rename_updates_the_registry_title(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")
    out = run_history(home, cwd, "--provider", "qoder", "rename", sid, "Новое имя")
    assert json.loads(out.stdout) == {"renamed": 1}
    assert registry_data(home)["qoder"][sid]["title"] == "Новое имя"


def test_delete_all_stays_inside_the_working_directory(tmp_path):
    """Superseded 2026-11-02: the sessions are deleted by qodercli itself, so
    the count follows what the CLI could remove — and the other directory's
    session stays in every case."""
    home = tmp_path / "home"
    here, there = tmp_path / "here", tmp_path / "there"
    here.mkdir()
    there.mkdir()
    sid_here, sid_there = "aaaa-1111", "bbbb-2222"
    path_here = make_qoder_session(home, here, sid_here)
    make_qoder_session(home, there, sid_there)
    run_history(home, here, "--provider", "qoder", "register", sid_here, "Здесь")
    run_history(home, there, "--provider", "qoder", "register", sid_there, "Там")
    out = run_history(home, here, "--provider", "qoder", "delete-all")
    # Without a qodercli that knows the session it cannot be removed. The
    # entry stays (the registry is the only listing) and the failure is
    # reported instead of silently hiding a live session.
    assert json.loads(out.stdout) == {"deleted": 0, "failed": 1}
    assert path_here.exists()
    left = registry_data(home).get("qoder", {})
    assert sid_here in left
    assert sid_there in left
