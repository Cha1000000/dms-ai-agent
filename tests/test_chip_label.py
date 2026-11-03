"""TDD: the model name in the chat's chip.

The toolbar chip has room for a short name only: a gateway model comes with
its vendor in front ("OpenAI · GPT 6 Astra"), and the whole name pushed the
buttons on that row out of the window. The chip therefore shows the bare
model name, cut to 18 characters; the picker keeps the full name with the
vendor.

Contract:
  - the vendor prefix is dropped ("OpenAI · GPT 6 Astra" -> "GPT 6 Astra")
  - a name without a vendor is left alone
  - a name longer than the limit is cut with an ellipsis, and the limit
    counts the ellipsis
  - the limit can be given per call
"""
import json
import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(__file__), "run_provider.js")

run = lambda fn, arg: json.loads(subprocess.run(
    ["node", NODE, fn, json.dumps(arg)], capture_output=True, text=True, check=True,
    cwd=PLUGIN,
).stdout)


def test_the_vendor_prefix_is_dropped():
    assert run("chipLabel", {"label": "OpenAI · GPT 6 Astra"}) == "GPT 6 Astra"
    assert run("chipLabel", {"label": "Moonshot AI · Kimi K2.8 Preview"}) == "Kimi K2.8 Preview"


def test_a_name_without_a_vendor_is_kept():
    assert run("chipLabel", {"label": "Claude Opus 5.5"}) == "Claude Opus 5.5"
    assert run("chipLabel", {"label": "Opus"}) == "Opus"


def test_a_long_name_is_cut():
    out = run("chipLabel", {"label": "Google · Gemini 3.8 Flash Preview"})
    assert len(out) <= 18, out
    assert out.endswith("…"), out
    assert out.startswith("Gemini 3.8"), out


def test_the_limit_is_configurable():
    out = run("chipLabel", {"label": "Claude Opus 5.5", "max": 8})
    assert len(out) <= 8, out
    assert out.startswith("Claude"), out
    assert out.endswith("…"), out


def test_an_empty_label_is_empty():
    assert run("chipLabel", {"label": ""}) == ""
