#!/usr/bin/env python3
"""OpenAI-compatible gateway bridge -> canonical claude stream-json.

Usage: openai_bridge.py <base-url>

base-url is checked by the caller against the registry (HTTPS, or HTTP only
for loopback). The API key is read from the provider registry (provider
secrets), never from argv or logs. Text chat only: tool calls are NOT part of
this adapter and a tool_use block is never fabricated.

stdin (from AgentService.qml), one JSON per line:
  {"type":"user","message":{"role":"user","content":[...]}}
  {"type":"config","resumeId":...}        (resume a local text session)
  {"type":"cancel"}

stdout: canonical assistant/result events. Exactly one result per turn.
  assistant deltas stream as they arrive;
  successful result carries the local session ID and usage.
"""
import json
import os
import subprocess
import sys
import threading
import queue
import time
import urllib.request
import urllib.error
import tempfile
import uuid

_state_lock = threading.Lock()
_state = {
    "turn_done": True,
    "cancel": False,
    "response": None,   # current HTTP response object (to close on cancel)
}

SYSTEM_PROMPT = ""       # set from the config line's systemPrompt if present
CONTEXT_FILE = ""        # one-shot context transfer (step 4), set by config
RESUME_ID = ""


def session_path(sid):
    parsed = uuid.UUID(sid)
    if parsed.version != 4 or str(parsed) != sid:
        raise ValueError("invalid session ID")
    state = os.path.expanduser(os.environ.get("XDG_STATE_HOME") or "~/.local/state")
    return os.path.join(state, "dms-agent", "openai-sessions", sid + ".json")


def load_session(sid):
    with open(session_path(sid), encoding="utf-8") as f:
        session = json.load(f)
    if (not isinstance(session, dict) or session.get("version") != 1
            or session.get("id") != sid or session.get("provider") != provider_id_from_env()
            or not isinstance(session.get("workDir"), str)
            or not isinstance(session.get("messages"), list)):
        raise ValueError("invalid session or provider mismatch")
    for message in session["messages"]:
        if (not isinstance(message, dict) or message.get("role") not in ("user", "assistant")
                or not isinstance(message.get("content"), str)):
            raise ValueError("invalid session message")
    return session


def save_session(session):
    path = session_path(session["id"])
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_context_messages():
    """Read the transfer file: [{"role":"user"|"assistant","content":str}].
    A missing/unreadable file is a turn error, never silently ignored."""
    if not CONTEXT_FILE:
        return []
    msgs = []
    with open(CONTEXT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if isinstance(d, dict) and d.get("role") in ("user", "assistant") \
                    and isinstance(d.get("content"), str):
                msgs.append({"role": d["role"], "content": d["content"]})
    return msgs


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_result(session_id, is_error, text, errors=None, usage=None):
    with _state_lock:
        if _state["turn_done"]:
            return
        _state["turn_done"] = True
    out({"type": "result", "session_id": session_id or "", "is_error": is_error,
         "result": text, "errors": errors or [], "total_cost_usd": None,
         "usage": usage})


def provider_id_from_env():
    return os.environ.get("DMS_AGENT_OPENAI_PROVIDER", "")


def api_key(pid):
    if not pid:
        return ""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import provider_secrets
        return provider_secrets.get_api_key(pid) or ""
    except Exception:
        return ""


def run_turn(msg, base_url, key):
    global RESUME_ID
    # The one-result guard must be armed BEFORE anything can fail: the 401 or
    # connection-error paths below emit the turn's result too.
    with _state_lock:
        _state["turn_done"] = False
        _state["cancel"] = False
        _state["response"] = None
    try:
        if RESUME_ID:
            session = load_session(RESUME_ID)
            context = []
        else:
            context = load_context_messages()
            session = {
                "version": 1,
                "id": str(uuid.uuid4()),
                "provider": provider_id_from_env(),
                "workDir": os.getcwd(),
                "messages": context[:],
            }
    except Exception as e:
        source = "local session" if RESUME_ID else "context file"
        emit_result("", True, "", ["cannot load %s: %s" % (source, e)])
        return
    content = msg.get("message", {}).get("content")
    if isinstance(content, str):
        user_text = content
    else:
        parts = []
        for c in content or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        user_text = "".join(parts)
    payload = {
        "model": os.environ.get("DMS_AGENT_OPENAI_MODEL", ""),
        "stream": True,
        "messages": ([{"role": "system", "content": SYSTEM_PROMPT}] if SYSTEM_PROMPT else [])
        + session["messages"]
        + [{"role": "user", "content": user_text}],
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "text/event-stream"},
        method="POST")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        resp = urllib.request.build_opener(NoRedirect()).open(req, timeout=600)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(2000).decode(errors="replace")
        except Exception:
            pass
        if 300 <= e.code < 400:
            emit_result("", True, "", ["gateway redirected (%s); the key is not sent to the new origin" % e.code])
        elif e.code == 401:
            emit_result("", True, "", ["gateway rejected the API key (401)"])
        else:
            emit_result("", True, "", ["gateway error %s: %s" % (e.code, body[:300])])
        return
    except Exception as e:
        emit_result("", True, "", ["connection failed: %s" % e])
        return
    with _state_lock:
        _state["response"] = resp

    text = ""
    usage = None
    errors = []
    saw_done = False
    try:
        for raw in resp:
            with _state_lock:
                if _state["cancel"]:
                    break
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                # Do not break: usage can arrive in the final chunk after
                # DONE in some gateways; read the stream to its end.
                saw_done = True
                continue
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            for ch in chunk.get("choices") or []:
                delta = ch.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    text += piece
                    out({"type": "assistant", "message": {"role": "assistant",
                                                          "content": [{"type": "text", "text": piece}]}})
            if chunk.get("usage"):
                usage = chunk["usage"]
    finally:
        try:
            resp.close()
        except Exception:
            pass
    cancelled = False
    with _state_lock:
        cancelled = _state["cancel"]
    if cancelled:
        if text:
            out({"type": "assistant", "message": {"role": "assistant",
                                                  "content": [{"type": "text", "text": text}]}})
        emit_result("", True, "", ["cancelled"])
        return
    if not saw_done:
        # The stream ended (EOF or connection drop) without [DONE]: an
        # incomplete answer is an error even if some text arrived — a "good"
        # empty result would hide the breakage.
        errors.append("connection closed before the answer finished")
    if errors:
        emit_result("", True, text, errors, usage)
        return
    session["messages"].extend([
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": text},
    ])
    try:
        save_session(session)
    except Exception as e:
        emit_result("", True, text, ["cannot save local session: %s" % e], usage)
        return
    RESUME_ID = session["id"]
    emit_result(RESUME_ID, False, text, usage=usage)


def do_cancel():
    with _state_lock:
        _state["cancel"] = True
        resp = _state["response"]
    if resp is not None:
        try:
            resp.close()  # unblocks the read loop immediately
        except Exception:
            pass


_turn_queue = queue.Queue()  # user messages; cancel/config handled inline


def stdin_loop():
    """stdin lives in its own thread: run_turn blocks the main loop while the
    turn streams, and the cancel the user sends must act right then —
    a single-threaded reader deadlocks (same trap as in acp/codex bridges)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mtype = msg.get("type")
        if mtype == "config":
            global SYSTEM_PROMPT, CONTEXT_FILE, RESUME_ID
            RESUME_ID = str(msg.get("resumeId") or "")
            if msg.get("systemPrompt"):

                SYSTEM_PROMPT = str(msg["systemPrompt"])
            if msg.get("contextFile"):
                CONTEXT_FILE = str(msg["contextFile"])
            else:
                CONTEXT_FILE = ""
            if msg.get("model"):
                os.environ["DMS_AGENT_OPENAI_MODEL"] = str(msg["model"])
        elif mtype == "cancel":
            do_cancel()
        elif mtype == "user":
            _turn_queue.put(msg)
    _turn_queue.put(None)  # EOF: finish the running turn, then exit.


def service_loop(base_url, key):
    while True:
        msg = _turn_queue.get()
        if msg is None:
            return
        run_turn(msg, base_url, key)


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.stderr.write("usage: openai_bridge.py <base-url>\n")
        sys.exit(2)
    base = sys.argv[1]
    host = base.split("://", 1)[-1].split("/", 1)[0]
    if base.startswith("http://") and not (host.startswith("127.0.0.1") or host.startswith("localhost")
                                           or host.startswith("[::1]") or host.startswith("[::]")):
        sys.stderr.write("openai_bridge: plain HTTP is only allowed for loopback\n")
        sys.exit(2)
    t = threading.Thread(target=stdin_loop, daemon=True)
    t.start()
    service_loop(base, api_key(provider_id_from_env()))


if __name__ == "__main__":
    main()
