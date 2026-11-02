"""TDD: the Qoder descriptor's MCP isolation (providers.js).

Measured 2026-11-02: `qodercli --mcp-config '{"mcpServers":{}}'
--strict-mcp-config` keeps the init event with `mcp_servers: []` and the run
still answers — so the chat never loads the helpers declared for the other
harnesses, and an unknown server cannot fail the run.
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


def test_run_loads_no_mcp_servers():
    cmd = run("qoder_buildCommand", {
        "model": "Qwen3.8-Flash", "effort": "", "confirm": False,
        "systemPrompt": "sp", "prompt": "p", "resumeId": "",
    })
    assert "--mcp-config '{\"mcpServers\":{}}'" in cmd
    assert "--strict-mcp-config" in cmd


def test_the_query_stays_a_positional_argument():
    # qodercli takes the prompt after `-p --`; a stdin query is not supported.
    # Unlike kimi, qoder has --append-system-prompt, so the two stay separate.
    cmd = run("qoder_buildCommand", {
        "model": "Qwen3.8-Flash", "effort": "", "confirm": False,
        "systemPrompt": "sp", "prompt": "say ok", "resumeId": "",
    })
    assert "--append-system-prompt 'sp'" in cmd
    assert "-p -- 'say ok'" in cmd
