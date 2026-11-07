"""TDD: общий перенос контекста между провайдерами (шаг 4 плана).

Контракт:
  - bridges принимают в config-строке "contextFile": путь к JSONL
    [{"role":"user"|"assistant","content":"текст"},...] — сообщения
    предшествуют текущему запросу; model/effort источника НЕ передаются;
  - файл 0600, во временном runtime-каталоге (создаёт вызывающий — QML);
  - мосты читают его на старте хода; ошибки чтения завершают ход с ошибкой,
    молчаливое игнорирование недопустимо;
  - после хода мост файл НЕ удаляет (порядок: удаляет сервис после result) —
    но повторное использование после успеха исключено: сервис задаёт
    contextFile только на первый ход переноса.
"""
import json
import os
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)
sys.path.insert(0, PLUGIN + "/tests")

import select
import subprocess
import tempfile
import time


def write_context(tmpdir, msgs):
    p = os.path.join(tmpdir, "ctx.jsonl")
    with open(p, "w") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    os.chmod(p, 0o600)
    return p


def read_one(stream, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([stream], [], [], 0.3)
        if not r:
            continue
        line = stream.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def user_msg(text):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "text", "text": text}]}}


# --- openai: context -> messages -------------------------------------------

def test_openai_bridge_sends_context_as_messages(tmp_path, monkeypatch):
    from test_openai_bridge import start_gateway, Bridge, Gateway
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("DMS_AGENT_OPENAI_PROVIDER", "mock-gateway")
    srv, base = start_gateway("sse")
    b = Bridge(base, env={"DMS_AGENT_OPENAI_MODEL": "m"})
    try:
        tmp = tempfile.mkdtemp()
        ctx = write_context(tmp, [{"role": "user", "content": "привет"},
                                  {"role": "assistant", "content": "здравствуй"}])
        b.send({"type": "config", "model": "m", "contextFile": ctx})
        b.send(user_msg("как дела?"))
        result = b.read_until_result()
        srv.shutdown()
        assert result is not None and result["is_error"] is False, result
        msgs = Gateway.seen_messages[0]
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "привет"
        assert msgs[1]["role"] == "assistant"
        assert msgs[-1] == {"role": "user", "content": "как дела?"}
        # model/effort источника не подмешиваются: в контексте их и нет.
    finally:
        b.close()


def test_openai_bridge_missing_context_file_fails_the_turn():
    from test_openai_bridge import start_gateway, Bridge
    srv, base = start_gateway("sse")
    b = Bridge(base, env={"DMS_AGENT_OPENAI_MODEL": "m"})
    try:
        b.send({"type": "config", "model": "m", "contextFile": "/no/such/file.jsonl"})
        b.send(user_msg("x"))
        result = b.read_until_result()
        srv.shutdown()
        assert result is not None and result["is_error"] is True, result
        assert "context" in " ".join(result["errors"]).lower()
    finally:
        b.close()


# --- codex: context -> prompt ------------------------------------------------

def test_codex_bridge_prepends_context_to_prompt():
    import test_codex_bridge as tcb
    import tempfile
    tmp = tempfile.mkdtemp()
    ctx = write_context(tmp, [{"role": "user", "content": "вопрос раз"},
                              {"role": "assistant", "content": "ответ раз"}])
    b = tcb.Bridge(["--stdin-echo"])
    try:
        b.send({"type": "config", "contextFile": ctx})
        b.send(user_msg("вопрос два"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        texts = [ev for ev in b.lines if ev.get("type") == "assistant"]
        # mock echo -> prompt содержит контекст и новый вопрос
        joined = "".join(c.get("text", "") for ev in texts
                         for c in ev["message"]["content"])
        assert "вопрос раз" in joined and "ответ раз" in joined
        assert "вопрос два" in joined
    finally:
        b.close()


# --- acp: context -> prompt content -----------------------------------------

def test_acp_bridge_prepends_context_to_prompt():
    import test_acp_bridge as tacp
    import tempfile
    tmp = tempfile.mkdtemp()
    ctx = write_context(tmp, [{"role": "user", "content": "вопрос раз"},
                              {"role": "assistant", "content": "ответ раз"}])
    b = tacp.Bridge(["--expect-config:model=m-big"])
    try:
        b.send({"type": "config", "model": "m-big", "contextFile": ctx})
        b.send(user_msg("вопрос два"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        # The mock echoes the prompt text back: the context must be in it.
        texts = [ev for ev in b.lines if ev.get("type") == "assistant"]
        joined = "".join(c.get("text", "") for ev in texts
                         for c in ev["message"]["content"])
        assert "вопрос раз" in joined and "ответ раз" in joined, joined
        assert "вопрос два" in joined, joined
    finally:
        b.close()


# --- perms -------------------------------------------------------------------

def test_context_file_is_owner_only(tmp_path):
    p = write_context(str(tmp_path), [{"role": "user", "content": "x"}])
    assert (os.stat(p).st_mode & 0o777) == 0o600


def test_qml_transfer_lifecycle_and_stale_writer():
    service = open(os.path.join(PLUGIN, "AgentService.qml")).read()
    assert 'os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW' in service
    assert 'onStarted: { write(input); stdinEnabled = false; }' in service
    assert 'cfg.contextFile = _pendingContextFile;' in service
    assert 'cfg.contextFile = _pendingContextFile;\n                    _pendingContextFile = "";' not in service
    assert 'if (data.is_error) {\n            if (_carriedContext.length > 0) rearmCarriedContext();\n            removeContextFile();' in service
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
function load(name, next) {
  const start = source.indexOf('    function ' + name + '(');
  const end = source.indexOf('    function ' + next + '(', start);
  assert(start >= 0 && end > start);
  vm.runInThisContext(source.slice(start, end));
}
load('collectCarried', 'carriedText');
load('carriedText', 'rearmCarriedContext');
load('rearmCarriedContext', 'removeContextFile');
load('removeContextFile', 'clearChatContext');
load('_launchClaude', '_launchChecked');
global.tr = x => x;
global.messages = [{role:'user', content:'old'}, {role:'assistant', content:'reply'}];
global._carriedContext = []; global._pendingContextFile = '';
global.shellQuote = x => "'" + x + "'";
global.removed = []; global.runQuietExit = x => removed.push(x);
rearmCarriedContext();
messages = [{role:'user', content:'new'}]; rearmCarriedContext();
assert.deepStrictEqual(_carriedContext.map(x => x.content), ['old','reply','new']);
rearmCarriedContext(); assert.equal(_carriedContext.length, 3);
global.providerOrClaude = {adapter:'openai', stdinUserFormat: x => x};
global.contextDir = '/tmp/test'; global._requestId = 5; global.statusText = '';
global.finished = ''; global.finishResponse = x => finished = x;
global.launched = []; global._launchNow = x => launched.push(x);
let props; global.contextWriter = {createObject: (_, p) => (props = p, {})}; global.root = {};
_launchClaude('hello');
assert(!JSON.stringify(props.path).includes('old'));
assert(props.input.includes('old'));
_requestId++; props.finished(0);
assert.equal(launched.length, 0); assert(removed.some(x => x.includes(props.path)));
_launchClaude('hello'); props.finished(0);
assert.equal(_pendingContextFile, props.path); assert.deepStrictEqual(launched, ['hello']);
removeContextFile(); assert.equal(_pendingContextFile, '');
assert(removed.some(x => x.includes(props.path)));
providerOrClaude = {stdinUserFormat:null}; _launchClaude('hello');
assert.equal(finished, ''); assert.equal(launched.length, 2);
assert(launched[1].includes('old') && launched[1].includes('hello'));
assert.deepStrictEqual(_carriedContext.map(x => x.content), ['old','reply','new']);
'''
    run = subprocess.run(["node", "-e", script, os.path.join(PLUGIN, "AgentService.qml")],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
