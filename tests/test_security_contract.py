import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.error

import pytest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)
import models  # noqa: E402


@pytest.mark.parametrize("override", [False, True])
def test_shared_registry_path_and_legacy_migration(tmp_path, override):
    home = tmp_path / "home"
    state = tmp_path / "state"
    target = tmp_path / "custom" / "providers.json" if override else state / "dms-agent" / "providers.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"cvc": {"apiKey": "fake-legacy-key"}}))
    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(state),
               PROVIDER_REGISTRY=str(target) if override else "",
               PROVIDER_SECRETS_STORE=str(tmp_path / "wrong.json"))

    def run(script, args, stdin=""):
        return subprocess.run([sys.executable, os.path.join(PLUGIN, script), *args],
                              input=stdin, text=True, capture_output=True, env=env, check=True)

    assert run("provider_secrets.py", ["get", "cvc"]).stdout == "fake-legacy-key"
    run("registry.py", ["set-provider", "example"], '{"adapter":"openai"}')
    run("provider_secrets.py", ["set", "other"], "fake-new-key\n")
    data = json.loads(target.read_text())
    assert data["keys"]["cvc"]["apiKey"] == "fake-legacy-key"
    assert data["keys"]["other"]["apiKey"] == "fake-new-key"
    assert data["providers"]["example"]["adapter"] == "openai"
    assert not (tmp_path / "wrong.json").exists()
    assert not (home / ".local/state/dms-agent/providers.json").exists()


@pytest.fixture
def servers():
    received = {"gateway": [], "destination": []}

    class Destination(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self):
            received["destination"].append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        do_GET = respond
        do_POST = respond

    dest = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Destination)

    class Gateway(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self):
            received["gateway"].append(self.headers.get("Authorization"))
            self.send_response(self.server.redirect_code)
            self.send_header("Location", "http://127.0.0.1:%d/stolen" % dest.server_port)
            self.end_headers()

        do_GET = respond
        do_POST = respond

    gateway = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    for server in (dest, gateway):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield gateway, received
    finally:
        for server in (gateway, dest):
            server.shutdown()
            server.server_close()


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_models_never_forward_authorization_on_redirect(servers, monkeypatch, code):
    gateway, received = servers
    gateway.redirect_code = code
    monkeypatch.setattr(models, "_registered", {"fake": {"baseUrl": "http://127.0.0.1:%d/v1" % gateway.server_port}})
    monkeypatch.setattr(models.provider_secrets, "get_api_key", lambda _: "fake-model-key")
    error = None
    try:
        models.ask_openai("fake")
    except urllib.error.HTTPError as exc:
        error = exc
    assert received["gateway"] == ["Bearer fake-model-key"]
    assert received["destination"] == []
    assert error is not None and error.code == code


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_bridge_never_forward_authorization_on_redirect(servers, tmp_path, code):
    gateway, received = servers
    gateway.redirect_code = code
    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"version": 1, "providers": {},
                                    "keys": {"fake": {"apiKey": "fake-bridge-key"}}}))
    env = dict(os.environ, HOME=str(tmp_path), PROVIDER_REGISTRY=str(registry),
               DMS_AGENT_OPENAI_PROVIDER="fake", no_proxy="127.0.0.1,localhost")
    msg = json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
    result = subprocess.run([sys.executable, os.path.join(PLUGIN, "bridges/openai_bridge.py"),
                             "http://127.0.0.1:%d/v1" % gateway.server_port],
                            input=msg, capture_output=True, text=True, env=env, timeout=10, check=True)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert received["gateway"] == ["Bearer fake-bridge-key"]
    assert received["destination"] == []
    assert len(events) == 1 and events[0]["is_error"] is True
    assert "redirect" in " ".join(events[0]["errors"]).lower()
    assert "fake-bridge-key" not in result.stdout + result.stderr
