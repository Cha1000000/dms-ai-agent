"""TDD: the Qoder model list.

Source is `qodercli --list-models` — a flat column of ids under a "MODEL"
header (there is no per-model metadata, so every model gets the same effort
set: the CLI's own --reasoning-effort enum). Contract from
tools/plans/jarvis-multi-provider.md, stage 3: "модели --list-models (flat id
как displayName); effort из константы".
"""
import json
import os
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_efforts_are_the_cli_enum_minus_auto_and_none():
    # qodercli --reasoning-effort accepts auto, none, low, medium, high, xhigh,
    # max, ultracode. "auto" is the empty chip (no flag) and "none" turns
    # reasoning off rather than tuning it, so the picker offers the rest.
    assert models.QODER_EFFORTS == ["low", "medium", "high", "xhigh", "max", "ultracode"]


def test_map_qoder_models_reads_the_flat_column():
    out = models.map_qoder_models("MODEL\nQwen3.8-Flash\nMy-Custom\n")
    assert [m["id"] for m in out] == ["Qwen3.8-Flash", "My-Custom"]
    for m in out:
        assert m["label"] == m["id"]
        assert m["resolved"] == m["id"]
        assert m["efforts"] == models.QODER_EFFORTS


def test_map_qoder_models_skips_header_and_blank_lines():
    out = models.map_qoder_models("MODEL\n\nQwen3.8-Flash\n   \n")
    assert [m["id"] for m in out] == ["Qwen3.8-Flash"]


def test_map_qoder_models_of_empty_output_is_empty():
    assert models.map_qoder_models("") == []
    assert models.map_qoder_models(None) == []


def _stub_bin(tmp_path, script_body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "qodercli"
    stub.write_text("#!/bin/sh\n" + script_body)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def run_models(home, cache_home, bin_dir):
    env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(cache_home),
               PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    env.pop("XDG_STATE_HOME", None)
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "models.py"), "--provider", "qoder"],
        env=env, capture_output=True, text=True,
    )


def test_fetch_wires_the_cli_output_through(tmp_path):
    bin_dir = _stub_bin(tmp_path, "printf 'MODEL\\nQwen3.8-Flash\\nMy-Custom\\n'\n")
    out = run_models(tmp_path / "home", tmp_path / "cache", bin_dir)
    assert out.returncode == 0, out.stderr
    models_out = json.loads(out.stdout)
    assert [m["id"] for m in models_out] == ["Qwen3.8-Flash", "My-Custom"]


def test_fetch_caches_what_the_cli_reported(tmp_path):
    bin_dir = _stub_bin(tmp_path, "printf 'MODEL\\nQwen3.8-Flash\\n'\n")
    cache_home = tmp_path / "cache"
    run_models(tmp_path / "home", cache_home, bin_dir)
    cached = cache_home / "dms-agent" / "models-qoder.json"
    assert [m["id"] for m in json.loads(cached.read_text())] == ["Qwen3.8-Flash"]


def test_dead_cli_falls_back_to_the_cache(tmp_path):
    cache_home = tmp_path / "cache"
    (cache_home / "dms-agent").mkdir(parents=True)
    (cache_home / "dms-agent" / "models-qoder.json").write_text(
        json.dumps([{"id": "Qwen3.8-Flash", "label": "Qwen3.8-Flash",
                     "resolved": "Qwen3.8-Flash", "desc": "", "efforts": []}]))
    bin_dir = _stub_bin(tmp_path, "echo 'qodercli: not logged in' >&2\nexit 1\n")
    out = run_models(tmp_path / "home", cache_home, bin_dir)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)[0]["id"] == "Qwen3.8-Flash"
