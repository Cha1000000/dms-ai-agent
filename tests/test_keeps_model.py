"""TDD: which saved model id survives a catalog change.

The chat stores one model per provider. When the provider's catalog changes
(the harness on PATH swapped its model list), the saved id may no longer exist
there — then --model would send an id the CLI rejects and every run fails.

Contract: an id survives when the new catalog lists it (by id or by the model
it resolves to). A bare alias ("opus") survives only while the catalog still
offers the aliases: under a harness aggregate there are none,
and there "opus" means the Combo, which must not be in Jarvis.
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

NATIVE = [{"id": "opus", "resolved": "opus"}, {"id": "sonnet", "resolved": "sonnet"},
          {"id": "haiku", "resolved": "haiku"}]
AGGREGATE = [{"id": "cvc/claude-opus-5-5", "resolved": "cvc/claude-opus-5-5"},
             {"id": "kc/google/gemini-2.5-flash", "resolved": "kc/google/gemini-2.5-flash"}]


def test_a_model_of_the_new_catalog_survives():
    assert run("keepsModel", {"provider": "claude", "models": NATIVE,
                              "saved": "opus"}) is True
    assert run("keepsModel", {"provider": "claude", "models": AGGREGATE,
                              "saved": "cvc/claude-opus-5-5"}) is True


def test_a_model_found_by_its_resolved_id_survives():
    models = [{"id": "opus", "resolved": "claude-opus-5-5"}]
    assert run("keepsModel", {"provider": "claude", "models": models,
                              "saved": "claude-opus-5-5"}) is True


def test_a_foreign_id_does_not_survive():
    assert run("keepsModel", {"provider": "claude", "models": AGGREGATE,
                              "saved": "kimi-k2.8-preview"}) is False
    assert run("keepsModel", {"provider": "cvc", "models": AGGREGATE,
                              "saved": "Qwen3.8-Flash"}) is False


def test_a_bare_alias_survives_only_while_the_catalog_offers_the_aliases():
    # Native catalog: "opus" is one of its entries — it stays.
    assert run("keepsModel", {"provider": "claude", "models": NATIVE,
                              "saved": "opus"}) is True
    # Harness aggregate: no aliases in the catalog, and "opus" there is the
    # Combo — which must not be in Jarvis.
    assert run("keepsModel", {"provider": "claude", "models": AGGREGATE,
                              "saved": "opus"}) is False


def test_a_provider_without_aliases_keeps_nothing_but_its_catalog():
    models = [{"id": "Qwen3.8-Flash", "resolved": "Qwen3.8-Flash"}]
    assert run("keepsModel", {"provider": "qoder", "models": models,
                              "saved": "Qwen3.8-Flash"}) is True
    assert run("keepsModel", {"provider": "qoder", "models": models,
                              "saved": "opus"}) is False
