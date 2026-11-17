"""TDD: Antigravity (agy acp) model catalog mapping and isolated probe."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Snapshot captured from `agy acp` 1.5.10 session/new response (2026-11-17).
SNAPSHOT = {
    "sessionId": "00000000-0000-0000-0000-000000000001",
    "models": {
        "currentModelId": "gemini-4-argon-medium",
        "availableModels": [
            {"modelId": "gemini-4-argon-low", "name": "Gemini 4 Argon (Low)"},
            {"modelId": "gemini-4-argon-medium", "name": "Gemini 4 Argon (Medium)"},
            {"modelId": "gemini-4-argon-high", "name": "Gemini 4 Argon (High)"},
            {"modelId": "gemini-4-hydrogen-low", "name": "Gemini 4 Hydrogen (Low)"},
            {"modelId": "gemini-4-hydrogen-medium", "name": "Gemini 4 Hydrogen (Medium)"},
            {"modelId": "gemini-4-hydrogen-high", "name": "Gemini 4 Hydrogen (High)"},
            {"modelId": "gemini-4-hydrogen-xhigh", "name": "Gemini 4 Hydrogen (XHigh)"},
            {"modelId": "gemini-pro-orchestrator-g1-pro", "name": "Orchestrator (Argon)"},
            {"modelId": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)"},
            {"modelId": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)"},
            {"modelId": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
            {"modelId": "claude-opus-5-5-low", "name": "Claude Opus 5.5 (Low)"},
            {"modelId": "claude-opus-5-5-medium", "name": "Claude Opus 5.5 (Medium)"},
            {"modelId": "claude-opus-5-5-high", "name": "Claude Opus 5.5 (High)"},
            {"modelId": "claude-sonnet-5-5-low", "name": "Claude Sonnet 5.5 (Low)"},
            {"modelId": "claude-sonnet-5-5-medium", "name": "Claude Sonnet 5.5 (Medium)"},
            {"modelId": "claude-sonnet-5-5-high", "name": "Claude Sonnet 5.5 (High)"},
            {"modelId": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
        ],
    },
    "configOptions": [
        {
            "id": "model",
            "name": "Model",
            "category": "model",
            "type": "select",
            "currentValue": "gemini-4-argon",
            "options": [
                {"value": "gemini-4-argon", "name": "Gemini 4 Argon"},
                {"value": "gemini-4-hydrogen", "name": "Gemini 4 Hydrogen"},
                {"value": "gemini-pro-orchestrator-g1-pro", "name": "Orchestrator (Argon)"},
                {"value": "gemini-3.8-flash", "name": "Gemini 3.8 Flash"},
                {"value": "claude-opus-5-5", "name": "Claude Opus 5.5"},
                {"value": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
                {"value": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
            ],
        },
        {
            "id": "thought_level",
            "name": "Thought Level",
            "category": "thought_level",
            "type": "select",
            "currentValue": "medium",
            "options": [
                {"value": "low", "name": "Low"},
                {"value": "medium", "name": "Medium"},
                {"value": "high", "name": "High"},
            ],
        },
    ],
}


def test_map_agy_models_preserves_seven_families_and_exact_efforts():
    rows = models.map_agy_models(SNAPSHOT)
    assert [r["id"] for r in rows] == [
        "gemini-4-argon",
        "gemini-4-hydrogen",
        "gemini-pro-orchestrator-g1-pro",
        "gemini-3.8-flash",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "gpt-oss-120b-medium",
    ]
    by_id = {r["id"]: r for r in rows}

    assert by_id["gemini-4-argon"]["label"] == "Gemini 4 Argon"
    assert by_id["gemini-4-argon"]["efforts"] == ["low", "medium", "high"]
    assert by_id["gemini-4-argon"]["desc"] == "Gemini"

    # Only Hydrogen offers xhigh in the real catalog even though initial
    # session/new thought_level only lists low/medium/high.
    assert by_id["gemini-4-hydrogen"]["efforts"] == ["low", "medium", "high", "xhigh"]

    assert by_id["claude-opus-5-5"]["desc"] == "Claude"
    assert by_id["claude-opus-5-5"]["efforts"] == ["low", "medium", "high"]
    assert by_id["claude-sonnet-5-5"]["desc"] == "Claude"

    # Models without suffix variants in availableModels get no effort chip;
    # gpt-oss-120b-medium must NOT be stripped to "gpt-oss-120b".
    assert by_id["gemini-pro-orchestrator-g1-pro"]["efforts"] == []
    assert by_id["gpt-oss-120b-medium"]["efforts"] == []
    assert by_id["gpt-oss-120b-medium"]["desc"] == ""

    for row in rows:
        assert row["resolved"] == row["id"]


def test_map_agy_models_filters_banned_ids_and_handles_empty():
    noisy = json.loads(json.dumps(SNAPSHOT))
    noisy["configOptions"][0]["options"].extend([
        {"value": "fable-preview", "name": "Fable"},
        {"value": "tk-free", "name": "Tokenator Free"},
    ])
    ids = [r["id"] for r in models.map_agy_models(noisy)]
    assert "fable-preview" not in ids
    assert "tk-free" not in ids
    assert models.map_agy_models(None) == []
    assert models.map_agy_models({}) == []


def test_ask_agy_probes_isolated_tempdir_and_returns_mapped_catalog(monkeypatch):
    seen = {}

    def fake_ask_acp_raw(cmd):
        seen["cmd"] = list(cmd)
        idx = cmd.index("--gemini-dir")
        seen["gemini_dir"] = cmd[idx + 1]
        seen["exists_during_call"] = os.path.isdir(seen["gemini_dir"])
        return SNAPSHOT

    monkeypatch.setattr(models, "ask_acp_raw", fake_ask_acp_raw)
    rows = models.fetch_models_for("agy")
    assert len(rows) == 7
    assert seen["cmd"][:2] == ["agy", "acp"]
    assert "--app-data-dir" in seen["cmd"]
    assert "agy-app" in seen["cmd"]
    assert "--include-default-customizations=false" in seen["cmd"]
    assert seen["exists_during_call"] is True
    # Temp dir must be cleaned up after catalog probe so no stale DBs linger.
    assert not os.path.exists(seen["gemini_dir"])


def test_models_cli_agy_caches_and_falls_back(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agy = bin_dir / "agy"
    agy.write_text(f"""#!{sys.executable}
import json, os, sys
if os.environ.get("AGY_FAIL") == "1":
    sys.exit(2)
snapshot = {json.dumps(SNAPSHOT)}
for line in sys.stdin:
    req = json.loads(line)
    rid, method = req.get("id"), req.get("method")
    if method == "initialize":
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": {{"protocolVersion": 1}}}}), flush=True)
    elif method == "session/new":
        print(json.dumps({{"jsonrpc": "2.0", "id": rid, "result": snapshot}}), flush=True)
        break
""")
    agy.chmod(0o755)
    cache_home = tmp_path / "cache"
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
               XDG_CACHE_HOME=str(cache_home), HOME=str(tmp_path))

    out = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "models.py"), "--provider", "agy"],
        env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    parsed = json.loads(out.stdout)
    assert [m["id"] for m in parsed] == [
        "gemini-4-argon", "gemini-4-hydrogen", "gemini-pro-orchestrator-g1-pro",
        "gemini-3.8-flash", "claude-opus-5-5", "claude-sonnet-5-5", "gpt-oss-120b-medium",
    ]
    cached_file = cache_home / "dms-agent" / "models-agy.json"
    assert cached_file.is_file()

    # Fallback to cache if CLI probe fails.
    env["AGY_FAIL"] = "1"
    out2 = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "models.py"), "--provider", "agy"],
        env=env, capture_output=True, text=True,
    )
    assert out2.returncode == 0, out2.stderr
    assert json.loads(out2.stdout) == parsed
