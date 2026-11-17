"""TDD: Antigravity (agy) session registry history and isolated file cleanup."""
import json
import os
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_history(state_home, cwd, *args):
    env = dict(os.environ, XDG_STATE_HOME=str(state_home), HOME=str(state_home.parent))
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), "--provider", "agy", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )


def create_agy_session_files(state_home, sid):
    app_dir = state_home / "dms-agent" / "agy-gemini" / "agy-app"
    for sub in ("conversations", "presence"):
        (app_dir / sub).mkdir(parents=True, exist_ok=True)
    (app_dir / "conversations" / f"{sid}.db").write_text("db")
    (app_dir / "conversations" / f"{sid}.db-wal").write_text("wal")
    (app_dir / "conversations" / f"{sid}.db-shm").write_text("shm")
    brain = app_dir / "brain" / sid
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "note.md").write_text("hi")
    (app_dir / "presence" / f"{sid}.lock").write_text("lock")
    return app_dir


def test_register_list_all_dirs_rename_and_tui_isolation(tmp_path):
    state = tmp_path / "state"
    w1 = tmp_path / "proj1"
    w2 = tmp_path / "proj2"
    w1.mkdir()
    w2.mkdir()

    # An unregistered DB file (e.g., stray/TUI session) must never show up.
    create_agy_session_files(state, "tui-only-sess")
    assert json.loads(run_history(state, w1, "list").stdout) == []

    assert json.loads(run_history(state, w1, "register", "agy-1", "First chat").stdout) == {"registered": 1}
    assert json.loads(run_history(state, w2, "register", "agy-2", "Second chat").stdout) == {"registered": 1}

    rows_w1 = json.loads(run_history(state, w1, "list").stdout)
    assert [(r["id"], r["title"]) for r in rows_w1] == [("agy-1", "First chat")]

    rows_all = json.loads(run_history(state, w1, "list", "--all-dirs").stdout)
    assert {r["id"]: r["workDir"] for r in rows_all} == {"agy-1": str(w1), "agy-2": str(w2)}

    assert json.loads(run_history(state, w1, "rename", "agy-1", "Renamed").stdout) == {"renamed": 1}
    assert json.loads(run_history(state, w1, "list").stdout)[0]["title"] == "Renamed"


def test_restore_keeps_registry_origin_dir(tmp_path):
    state = tmp_path / "state"
    work = tmp_path / "proj"
    work.mkdir()
    run_history(state, work, "register", "agy-1", "Demo")
    data = json.loads(run_history(state, work, "restore", "agy-1").stdout)
    assert data == {"messages": [], "model": "", "effort": "", "originDir": str(work)}


def test_delete_cleans_isolated_session_files_and_keeps_siblings(tmp_path):
    state = tmp_path / "state"
    work = tmp_path / "proj"
    work.mkdir()
    app_dir = create_agy_session_files(state, "agy-1")
    create_agy_session_files(state, "agy-keep")
    run_history(state, work, "register", "agy-1", "Delete me")
    run_history(state, work, "register", "agy-keep", "Keep me")

    out = json.loads(run_history(state, work, "delete", "agy-1").stdout)
    assert out == {"deleted": 1, "removed": 1}

    assert not (app_dir / "conversations" / "agy-1.db").exists()
    assert not (app_dir / "conversations" / "agy-1.db-wal").exists()
    assert not (app_dir / "conversations" / "agy-1.db-shm").exists()
    assert not (app_dir / "brain" / "agy-1").exists()
    assert not (app_dir / "presence" / "agy-1.lock").exists()

    # Sibling session files and entry are untouched.
    assert (app_dir / "conversations" / "agy-keep.db").is_file()
    assert (app_dir / "brain" / "agy-keep" / "note.md").is_file()
    assert (app_dir / "presence" / "agy-keep.lock").is_file()
    assert [r["id"] for r in json.loads(run_history(state, work, "list").stdout)] == ["agy-keep"]


def test_delete_rejects_path_traversal(tmp_path):
    state = tmp_path / "state"
    work = tmp_path / "proj"
    work.mkdir()
    sentinel = state / "dms-agent" / "important.db"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("keep")

    for bad_id in ("../important", "../../etc/passwd", "a/b", ".."):
        out = json.loads(run_history(state, work, "delete", bad_id).stdout)
        assert out == {"deleted": 0, "removed": 0}
    assert sentinel.is_file()


def test_delete_all_scopes_to_cwd(tmp_path):
    state = tmp_path / "state"
    w1 = tmp_path / "p1"
    w2 = tmp_path / "p2"
    w1.mkdir()
    w2.mkdir()
    app_dir = create_agy_session_files(state, "agy-1")
    create_agy_session_files(state, "agy-2")
    run_history(state, w1, "register", "agy-1", "Here")
    run_history(state, w2, "register", "agy-2", "There")

    out = json.loads(run_history(state, w1, "delete-all").stdout)
    assert out == {"deleted": 1, "failed": 0}
    assert not (app_dir / "conversations" / "agy-1.db").exists()
    assert (app_dir / "conversations" / "agy-2.db").is_file()
    assert [r["id"] for r in json.loads(run_history(state, w2, "list").stdout)] == ["agy-2"]
