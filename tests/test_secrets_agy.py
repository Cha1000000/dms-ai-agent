"""TDD: Antigravity (agy) login check via system keyring (secret-tool)."""
import json
import os
import subprocess
import sys

import pytest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

import provider_secrets as ps  # noqa: E402
import registry  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    reg_path = tmp_path / "providers.json"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(reg_path))
    monkeypatch.setenv("PROVIDER_REGISTRY", str(reg_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path


def _install_secret_tool(tmp_path, monkeypatch, script_body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    tool = bin_dir / "secret-tool"
    tool.write_text("#!/bin/sh\n" + script_body)
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return tool


def test_valid_keyring_token_is_signed_in(isolated, monkeypatch):
    payload = json.dumps({
        "token": {"access_token": "at-secret-1", "refresh_token": "rt-secret-2"},
        "auth_method": "oauth-personal",
    })
    _install_secret_tool(
        isolated, monkeypatch,
        '[ "$1 $2 $3 $4 $5" = "lookup service gemini username antigravity" ] || exit 1\n'
        f"printf '%s' '{payload}'\n",
    )
    assert ps.is_signed_in("agy") is True


def test_missing_or_empty_keyring_entry_is_not_signed_in(isolated, monkeypatch):
    _install_secret_tool(isolated, monkeypatch, "exit 1\n")
    assert ps.is_signed_in("agy") is False

    _install_secret_tool(isolated, monkeypatch, "printf ''\n")
    assert ps.is_signed_in("agy") is False


def test_malformed_or_tokenless_keyring_json_is_not_signed_in(isolated, monkeypatch):
    _install_secret_tool(isolated, monkeypatch, "printf '{not json'\n")
    assert ps.is_signed_in("agy") is False

    _install_secret_tool(isolated, monkeypatch, "printf '{\"token\":{}}'\n")
    assert ps.is_signed_in("agy") is False


def test_missing_secret_tool_fails_open(isolated, monkeypatch):
    monkeypatch.setenv("PATH", str(isolated / "empty-bin"))
    assert ps.is_signed_in("agy") is True


def test_secret_tool_error_fails_open(isolated, monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.SubprocessError("keyring locked")

    _install_secret_tool(isolated, monkeypatch, "exit 0\n")
    monkeypatch.setattr(subprocess, "run", boom)
    assert ps.is_signed_in("agy") is True


def test_secret_tool_dbus_stderr_error_fails_open(isolated, monkeypatch):
    _install_secret_tool(
        isolated, monkeypatch,
        'echo "Error calling StartServiceByName for org.freedesktop.secrets" >&2; exit 1\n',
    )
    assert ps.is_signed_in("agy") is True


def test_cli_check_never_leaks_token(isolated, monkeypatch):
    secret = "rt-super-secret-do-not-print"
    payload = json.dumps({"token": {"refresh_token": secret}})
    _install_secret_tool(isolated, monkeypatch, f"printf '%s' '{payload}'\n")
    out = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "provider_secrets.py"), "check", "agy"],
        env=dict(os.environ), capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == "set"
    assert secret not in out.stdout
    assert secret not in out.stderr
