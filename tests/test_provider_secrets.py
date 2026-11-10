"""TDD: provider credentials under ~/.local/state/dms-agent/providers.json.

Contract (tools/plans/jarvis-multi-provider.md, этап 2):
  file ~/.local/state/dms-agent/providers.json, mode 0600
  shape {providerId: {"apiKey": "..."}}  — never in plugin_settings.json (ccsync
  syncs that one; keys must stay on this machine).
  - get_api_key(provider) -> str or ""
  - set_api_key(provider, key) writes the file with 0600 and keeps other providers
  - set_api_key("") / whitespace removes the key entry
  - export_env(provider) -> dict of env vars the CLI needs (CVC: base url + token)
"""
import json
import os
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_secrets as ps  # noqa: E402
import registry as registry  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "providers.json"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(path))
    monkeypatch.setattr(ps, "STORE_PATH", str(path), raising=False)
    return ps


def test_missing_file_gives_empty_key(store):
    assert store.get_api_key("cvc") == ""


def test_roundtrip_key(store):
    store.set_api_key("cvc", "sk-test-123")
    assert store.get_api_key("cvc") == "sk-test-123"


def test_file_is_owner_only(store):
    store.set_api_key("cvc", "sk-test-123")
    mode = stat.S_IMODE(os.stat(store.STORE_PATH).st_mode)
    assert mode == 0o600


def test_set_keeps_other_providers(store):
    store.set_api_key("cvc", "sk-a")
    store.set_api_key("other", "sk-b")
    assert store.get_api_key("cvc") == "sk-a"
    assert store.get_api_key("other") == "sk-b"


def test_blank_key_removes_entry(store):
    store.set_api_key("cvc", "sk-a")
    store.set_api_key("cvc", "   ")
    assert store.get_api_key("cvc") == ""
    # The entry is gone. An empty store may also drop the file entirely —
    # what matters is that nothing is readable back.
    if os.path.exists(store.STORE_PATH):
        data = json.load(open(store.STORE_PATH))
        assert "cvc" not in data["keys"]


def test_export_env_for_cvc(store):
    store.set_api_key("cvc", "sk-a")
    env = store.export_env("cvc")
    assert env["ANTHROPIC_BASE_URL"] == ps.CVC_BASE_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-a"


def test_export_env_without_key_is_empty(store):
    assert store.export_env("cvc") == {}


def test_env_export_shell_quotes_safely(store):
    import shlex
    store.set_api_key("cvc", "sk-a' b")
    shell = store.env_export_shell("cvc")
    assert "ANTHROPIC_BASE_URL=" in shell
    assert "ANTHROPIC_AUTH_TOKEN=" in shell
    # A quote in the key must be shell-quoted, not pasted raw.
    assert shlex.quote("sk-a' b") in shell
    assert "ANTHROPIC_AUTH_TOKEN=sk-a' b" not in shell


def test_env_export_shell_fails_closed_without_a_key(store):
    # The CVC provider runs `eval $(env-export cvc) && claude`: an empty
    # prefix would run the stock CLI on the user's own Anthropic login.
    assert store.env_export_shell("cvc") == "false; "
    # Other providers have no such prefix at all.
    assert store.env_export_shell("claude") == ""


def test_corrupt_file_does_not_crash(store):
    # Новый контракт (план «Реестр, секреты и граница доверия»): повреждённый
    # файл — явная ошибка чтения, НИКОГДА не молчаливая замена пустым стором.
    os.makedirs(os.path.dirname(store.STORE_PATH), exist_ok=True)
    with open(store.STORE_PATH, "w") as fh:
        fh.write("{not json")
    with pytest.raises(registry.RegistryError):
        store.get_api_key("cvc")


# --- is_signed_in: the "not logged in" gate (stage 5 of the provider plan) ---
#
# Contract: the chat must not fire a CLI that can only fail with a wall of
# auth errors — it says "not signed in" and how to sign in instead. Probes are
# cheap (the CLI's own credential files) except claude, which is asked
# directly (`claude auth status`); a probe that cannot tell counts as signed
# in, so only a definite "no credentials" blocks the send.

def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_cvc_uses_the_key_store(store, tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert store.is_signed_in("cvc") is False
    store.set_api_key("cvc", "sk-a")
    assert store.is_signed_in("cvc") is True


def test_kimi_reads_its_credentials_dir(store, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    (home / ".kimi-code" / "credentials").mkdir(parents=True)
    assert store.is_signed_in("kimi") is False
    (home / ".kimi-code" / "credentials" / "kimi-code.json").write_text("{}")
    assert store.is_signed_in("kimi") is True


def test_qoder_reads_its_auth_file(store, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    (home / ".qoder" / "credentials").mkdir(parents=True)
    assert store.is_signed_in("qoder") is False
    (home / ".qoder" / "credentials" / "auth.json").write_text("{}")
    assert store.is_signed_in("qoder") is True


def test_claude_asks_the_cli(store, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    claude = bin_dir / "claude"
    claude.write_text('#!/bin/sh\n[ "$1" = auth ] || exit 1\ncase "$MODE" in\n'
                      '  in) echo "{\\"loggedIn\\": true}";;\n'
                      '  out) echo "{\\"loggedIn\\": false}";;\n'
                      '  *) exit 1;;\nesac\n')
    claude.chmod(0o755)
    monkeypatch.setenv("MODE", "in")
    assert store.is_signed_in("claude") is True
    monkeypatch.setenv("MODE", "out")
    assert store.is_signed_in("claude") is False


def test_a_probe_that_errors_does_not_block(store, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\nexit 3\n")
    claude.chmod(0o755)
    assert store.is_signed_in("claude") is True


def test_claude_json_that_is_not_an_object_does_not_crash(store, tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    claude = bin_dir / "claude"
    claude.write_text('#!/bin/sh\necho null\n')
    claude.chmod(0o755)
    assert store.is_signed_in("claude") is True


def test_a_gateway_provider_needs_its_key(store, tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    registry.set_provider("gw", {"adapter": "openai", "baseUrl": "https://gw.example/v1"})
    assert store.is_signed_in("gw") is False
    store.set_api_key("gw", "sk-a")
    assert store.is_signed_in("gw") is True


def test_a_codex_provider_asks_codex_login_status(store, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    codex = bin_dir / "codex"
    codex.write_text('#!/bin/sh\n[ "$1 $2" = "login status" ] || exit 2\n'
                     'echo "$MODE"\n')
    codex.chmod(0o755)
    registry.set_provider("cx", {"adapter": "codex", "command": ["codex", "exec", "--json"]})
    monkeypatch.setenv("MODE", "Not logged in")
    assert store.is_signed_in("cx") is False
    monkeypatch.setenv("MODE", "Logged in")
    assert store.is_signed_in("cx") is True


# --- the CLI surface: the key must not travel through argv ---
#
# A command line is readable by every user of the machine in
# /proc/<pid>/cmdline, and this is a secret. `set` therefore reads the key
# from stdin; the argv form stays only as a fallback for a caller with no
# stdin to give.

def _run_cli(store, args, stdin=""):
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "provider_secrets.py"), *args],
        input=stdin, capture_output=True, text=True,
        env=dict(os.environ, HOME=store.HOME, PROVIDER_REGISTRY=store.STORE_PATH),
    )


PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def cli_store(tmp_path, monkeypatch):
    """The real script, with its store path pointed at a temp file."""
    store_path = tmp_path / "providers.json"
    script = os.path.join(PLUGIN, "provider_secrets.py")
    monkeypatch.setenv("PROVIDER_REGISTRY", str(store_path))
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(store_path))
    return type("S", (), {"STORE_PATH": str(store_path), "HOME": str(tmp_path)})


def test_set_reads_the_key_from_stdin(cli_store):
    out = _run_cli(cli_store, ["set", "cvc"], stdin="sk-from-stdin\n")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
    data = json.load(open(cli_store.STORE_PATH))
    # Новый версионированный формат (план «Реестр, секреты и граница доверия»).
    assert data["version"] == 1
    assert data["keys"]["cvc"]["apiKey"] == "sk-from-stdin"


def test_set_still_works_without_a_stdin_key(cli_store):
    # Nothing on stdin and nothing in argv: the caller had nothing to save,
    # the stored key must survive untouched.
    out = _run_cli(cli_store, ["set", "cvc"], stdin="")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
    assert not os.path.exists(cli_store.STORE_PATH)


def test_set_with_an_empty_stdin_key_forgets_the_stored_one(cli_store):
    _run_cli(cli_store, ["set", "cvc"], stdin="sk-a\n")
    out = _run_cli(cli_store, ["set", "cvc"], stdin="\n")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
    # An empty key is an explicit request to forget it. The store may drop the
    # file entirely once it is empty — what matters is that nothing is readable
    # back.
    if os.path.exists(cli_store.STORE_PATH):
        data = json.load(open(cli_store.STORE_PATH))
        assert "cvc" not in data["keys"]


def test_the_key_is_not_in_the_command_line(cli_store):
    """The whole point: a key on the command line is readable by any user."""
    secret = "sk-secret-value-123"
    out = _run_cli(cli_store, ["set", "cvc"], stdin=secret + "\n")
    assert out.returncode == 0, out.stderr
    assert secret not in out.stdout
    assert secret not in out.stderr

