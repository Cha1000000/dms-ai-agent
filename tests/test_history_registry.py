"""TDD: общая история по реестру провайдеров (шаг 2 плана dms-glittery-sketch).

Контракт:
  - провайдер из providers.json с адаптером acp/codex/openai — «реестровый»:
    история из sessions_registry, как у qoder/kimi; сканировать его транскрипты
    плагин не умеет;
  - список с --all-dirs отдаёт сессии Jarvis из ВСЕХ каталогов, каждая запись
    несёт workDir и provider (составная идентичность);
  - в дефолтном списке (без --all-dirs) остаются только сессии текущего cwd;
  - совпадающий id у разных провайдеров — разные сессии, не склеиваются;
  - delete реестрового провайдера снимает запись сессии и не трогает чужие
    файлы (у этих CLI нет транскриптов, которые мы удаляем вручную);
  - неизвестный провайдер (не в коде и не в providers.json) — ошибка, а не
    молчаливая подмена claude.
"""
import json
import os
import subprocess
import sys

import pytest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

import sessions_registry as sr  # noqa: E402
import registry as prov_reg  # noqa: E402


@pytest.fixture
def state(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
    monkeypatch.setattr(sr, "REGISTRY_PATH", sr._registry_path())
    monkeypatch.setattr(prov_reg, "REGISTRY_PATH", prov_reg._registry_path())
    prov_reg.set_provider("my-acp", {"title": "ACP тест", "adapter": "acp"})
    prov_reg.set_provider("my-codex", {"title": "Codex тест", "adapter": "codex"})
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return {"state": state_dir, "work": str(work)}


def run_history(args, cwd=None):
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), *args],
        capture_output=True, text=True, cwd=cwd,
        env=dict(os.environ),
    )


def test_registry_provider_is_accepted(state):
    run = run_history(["--provider=my-acp", "list"])
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == []


def test_unknown_provider_is_rejected(state):
    run = run_history(["--provider=brainfuck", "list"])
    assert run.returncode == 2
    assert "unknown provider" in run.stderr


def test_corrupt_provider_registry_does_not_kill_builtin_history(state):
    (state["state"] / "dms-agent" / "providers.json").write_text("{not json")
    run = run_history(["--provider=claude", "list"])
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == []
    # Неизвестный поверх битого реестра всё равно отвергается.
    run = run_history(["--provider=brainfuck", "list"])
    assert run.returncode == 2


def test_registry_provider_lists_own_sessions(state):
    sr.add("my-acp", "s1", "Первый диалог", state["work"])
    sr.add("my-acp", "s2", "Второй", state["work"])
    run = run_history(["--provider=my-acp", "list"])
    rows = json.loads(run.stdout)
    assert [r["id"] for r in rows] == ["s2", "s1"]
    assert rows[0]["workDir"] == state["work"]


def test_default_list_filters_by_cwd(state):
    sr.add("my-acp", "here", "Тут", state["work"])
    sr.add("my-acp", "elsewhere", "Там", "/somewhere/else")
    run = run_history(["--provider=my-acp", "list"])
    assert [r["id"] for r in json.loads(run.stdout)] == ["here"]


def test_all_dirs_lists_every_directory(state):
    sr.add("my-acp", "here", "Тут", state["work"])
    sr.add("my-acp", "elsewhere", "Там", "/somewhere/else")
    sr.add("my-codex", "third", "Третья", "/third/place")
    run = run_history(["--provider=my-acp", "list", "--all-dirs"])
    rows = json.loads(run.stdout)
    assert {r["id"] for r in rows} == {"here", "elsewhere"}
    by_id = {r["id"]: r for r in rows}
    assert by_id["elsewhere"]["workDir"] == "/somewhere/else"


def test_same_id_in_two_providers_stays_two_sessions(state):
    sr.add("my-acp", "dup", "От ACP", state["work"])
    sr.add("my-codex", "dup", "От Codex", state["work"])
    rows_a = json.loads(run_history(["--provider=my-acp", "list"]).stdout)
    rows_c = json.loads(run_history(["--provider=my-codex", "list"]).stdout)
    assert rows_a[0]["title"] == "От ACP"
    assert rows_c[0]["title"] == "От Codex"


def test_delete_removes_registry_entry_only(state):
    sr.add("my-acp", "gone", "Сносим", state["work"])
    run = run_history(["--provider=my-acp", "delete", "gone"])
    assert json.loads(run.stdout) == {"deleted": 1}
    assert sr.list("my-acp") == []


def test_delete_unknown_id_reports_failure(state):
    run = run_history(["--provider=my-acp", "delete", "nope"])
    assert run.returncode == 0
    assert json.loads(run.stdout) == {"deleted": 0}
