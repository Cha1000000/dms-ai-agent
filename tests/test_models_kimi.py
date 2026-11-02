"""TDD: the Kimi model list.

Source is ~/.kimi-code/config.toml (read-only — the CLI owns that file and
shares it with the user's own Kimi sessions). Each [models."provider/alias"]
block carries display_name and an optional support_efforts list. Contract from
tools/plans/jarvis-multi-provider.md, stage 4: "модели из config.toml
(read-only)".

Facts the fixtures mirror (checked on kimi 2.4.1, 2026-11-02):
  - model keys look like "kimi-code/k3.1-pro" and are exactly what `-m` takes
    (a bare "k3" is rejected: 'Model "k3" is not configured in config.toml');
  - support_efforts is low/high/max where present, and missing entirely on the
    highspeed models — those then get no effort chip at all.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG = """
default_model = "kimi-code/k3.1-pro"

[models."kimi-code/k3.1-pro"]
provider = "managed:kimi-code"
model = "k3.1-pro"
display_name = "K3.1 Pro"
support_efforts = [ "low", "high", "max" ]
default_effort = "high"

[models."kimi-code/k3.1-pro-highspeed"]
provider = "managed:kimi-code"
model = "k3.1-pro-highspeed"
display_name = "K3.1 Pro Highspeed 2x Usage Cost"
support_efforts = [ "low", "high", "max" ]

[models."kimi-code/kimi-for-coding-highspeed"]
provider = "managed:kimi-code"
model = "kimi-for-coding-highspeed"
display_name = "K.7 Code Highspeed"
"""


def test_map_kimi_models_reads_keys_names_and_efforts():
    out = models.map_kimi_models(CONFIG)
    by_id = {m["id"]: m for m in out}
    assert set(by_id) == {
        "kimi-code/k3.1-pro",
        "kimi-code/k3.1-pro-highspeed",
        "kimi-code/kimi-for-coding-highspeed",
    }
    pro = by_id["kimi-code/k3.1-pro"]
    assert pro["label"] == "K3.1 Pro"
    assert pro["resolved"] == "kimi-code/k3.1-pro"
    assert pro["efforts"] == ["low", "high", "max"]


def test_map_kimi_models_without_support_efforts_gets_no_chip():
    out = models.map_kimi_models(CONFIG)
    by_id = {m["id"]: m for m in out}
    assert by_id["kimi-code/kimi-for-coding-highspeed"]["efforts"] == []


def test_map_kimi_models_of_empty_config_is_empty():
    assert models.map_kimi_models("") == []
    assert models.map_kimi_models(None) == []


def _write_home(tmp_path, config_text):
    home = tmp_path / "home"
    (home / ".kimi-code").mkdir(parents=True)
    (home / ".kimi-code" / "config.toml").write_text(config_text)
    return home


def run_models(home, cache_home):
    env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(cache_home))
    env.pop("XDG_STATE_HOME", None)
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "models.py"), "--provider", "kimi"],
        env=env, capture_output=True, text=True,
    )


def test_fetch_reads_the_users_config(tmp_path):
    home = _write_home(tmp_path, CONFIG)
    out = run_models(home, tmp_path / "cache")
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert "kimi-code/k3.1-pro" in ids


def test_fetch_caches_the_list(tmp_path):
    home = _write_home(tmp_path, CONFIG)
    cache_home = tmp_path / "cache"
    run_models(home, cache_home)
    cached = cache_home / "dms-agent" / "models-kimi.json"
    assert "kimi-code/k3.1-pro" in [m["id"] for m in json.loads(cached.read_text())]


def test_missing_config_falls_back_to_the_cache(tmp_path):
    cache_home = tmp_path / "cache"
    (cache_home / "dms-agent").mkdir(parents=True)
    (cache_home / "dms-agent" / "models-kimi.json").write_text(
        json.dumps([{"id": "kimi-code/k3", "label": "K3", "resolved": "kimi-code/k3",
                     "desc": "", "efforts": ["low", "high", "max"]}]))
    out = run_models(tmp_path / "nobody", cache_home)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)[0]["id"] == "kimi-code/k3"
