"""TDD: the capability flags the chat reads (providers.js).

Every provider descriptor states what its CLI can do, and the chat must obey
those statements instead of guessing:

  cost          - whether the CLI reports a price at all. Qoder and Kimi
                  answer with total_cost_usd 0 and empty token counts, so a
                  price line for them is "$0.0000 (0→0 tokens)" — noise.
  stdinEnabled  - whether the CLI takes the next message from stdin. The
                  voice buttons stay visible while the agent answers only for
                  such a provider; the others would need a second run.
"""
import json
import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_provider.js")

run = lambda fn, arg=None: json.loads(subprocess.run(
    ["node", NODE, fn, json.dumps(arg or {})], capture_output=True, text=True, check=True,
    cwd=PLUGIN,
).stdout)

CAPS_FN = {"claude": "claude_caps", "cvc": "cvc_caps",
           "qoder": "qoder_caps", "kimi": "kimi_caps"}


def _caps(provider):
    return run(CAPS_FN[provider])["caps"]


def test_only_claude_and_cvc_report_a_price():
    assert _caps("claude")["cost"] is True
    assert _caps("cvc")["cost"] is True
    assert _caps("qoder")["cost"] is False
    assert _caps("kimi")["cost"] is False


def test_only_claude_and_cvc_read_the_next_message_from_stdin():
    assert _caps("claude")["stdinEnabled"] is True
    assert _caps("cvc")["stdinEnabled"] is True
    assert _caps("qoder")["stdinEnabled"] is False
    assert _caps("kimi")["stdinEnabled"] is False
