#!/usr/bin/env python3
"""Codex bridge: `codex exec --json` -> canonical claude stream-json for
DMS Agent.

Usage: codex_bridge.py <codex-command...>
(e.g. codex_bridge.py codex  or  codex_bridge.py /path/to/mock_codex_cli.py)

The bridge invokes the command as
  <cmd...> exec [--json] [-m MODEL] [-c model_reasoning_effort="E"] -
and for a resume turn
  <cmd...> exec resume <id> [--json] [-m MODEL] [...] -
The prompt arrives on stdin ("-"): it never appears in argv or logs.

stdin  (from AgentService.qml):
  {"type":"config","model":...,"effort":...,"resumeId":...}
  {"type":"user","message":{"role":"user","content":[...canon...]}}
  {"type":"cancel"}

stdout (to AgentService.qml), canonical claude stream-json:
  {"type":"assistant","message":{"content":[...]}}
  {"type":"result","session_id":thread_id,"is_error":bool,"result":str,
   "errors":[...],"total_cost_usd":null,"usage":{...}|null}

Event mapping (verified live against codex-cli 0.166.0):
  thread.started          -> captured as session_id, not emitted
  turn.started            -> nothing
  item.completed agent_message -> assistant text (fields text or content[].text)
  item.completed error    -> collected; the turn ends with is_error=true
  turn.completed          -> result is_error per collected errors, usage passed
  turn.failed             -> result is_error=true with error.message
  {"type":"error"} lines  -> transport-level retries/noise: collected into the
                             result errors but they do NOT end the turn
  non-JSON lines          -> ignored
Exactly one result per turn. EOF before turn completion -> result is_error.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import queue
import time

_state_lock = threading.Lock()
_state = {
    "config": {},          # model / effort / resumeId
    "turn_done": True,
    "proc": None,
    "cancelled": False,
}

_errors = []               # errors collected for the current turn
_thread_id = ""            # session id from thread.started


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def send_result(session_id, is_error, text, errors=None, usage=None):
    out({"type": "result", "session_id": session_id or "", "is_error": is_error,
         "result": text, "errors": errors or [], "total_cost_usd": None,
         "usage": usage})


def emit_result(session_id, is_error, text, errors=None, usage=None):
    with _state_lock:
        if _state["turn_done"]:
            return
        _state["turn_done"] = True
    send_result(session_id, is_error, text, errors, usage)


def load_context_text():
    """One-shot context transfer: [{"role","content"}] JSONL -> a transcript
    block prepended to the first turn. A missing/unreadable file is a turn
    error, never silently ignored."""
    path = ""
    with _state_lock:
        path = _state["config"].get("contextFile", "")
    if not path:
        return ""
    parts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if isinstance(d, dict) and d.get("role") in ("user", "assistant") \
                    and isinstance(d.get("content"), str):
                parts.append("%s: %s" % ("User" if d["role"] == "user" else "Assistant",
                                         d["content"]))
    if not parts:
        return ""
    return "Previous conversation (carried over from another provider):\n" \
        + "\n".join(parts) + "\n\n"


def canon_text(content):
    blocks = content if isinstance(content, list) else [content]
    parts = []
    for c in blocks:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif isinstance(c, str):
            parts.append(c)
    return "".join(parts)


def item_text(item):
    if isinstance(item.get("text"), str):
        return item["text"]
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                t = c.get("text") or c.get("output_text") or ""
                if t:
                    parts.append(t)
        return "".join(parts)
    return ""


def build_argv(cmd, resume_id):
    cfg = {}
    with _state_lock:
        cfg = dict(_state["config"])
    base = list(cmd) + ["exec"]
    if resume_id:
        # `codex exec resume` accepts --json/-c/--skip-git-repo-check but NOT
        # --color (codex-cli 0.167: "unexpected argument '--color' found"), so
        # the flag belongs to the first turn only.
        base += ["resume", resume_id, "--json", "--skip-git-repo-check", "-"]
    else:
        base += ["--json", "--skip-git-repo-check", "--color", "never", "-"]
    if cfg.get("model"):
        base += ["-m", cfg["model"]]
    effort = cfg.get("effort")
    # The value becomes a TOML fragment in -c: anything with a quote or a
    # newline would inject more config. Levels are plain words.
    if effort and re.fullmatch(r"[A-Za-z0-9_-]+", str(effort)):
        base += ["-c", 'model_reasoning_effort="%s"' % effort]
    return base


def reader(proc):
    """Read codex stdout; map events to canonical ones; emit one result."""
    errors = []
    warnings = []
    thread_id = ""
    usage = None
    turn_done = False
    saw_turn_start = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue  # banner/transport noise
            etype = ev.get("type")
            if etype == "thread.started":
                thread_id = ev.get("thread_id", "")
            elif etype == "turn.started":
                saw_turn_start = True
            elif etype == "item.completed":
                item = ev.get("item") or {}
                itype = item.get("type")
                if itype == "agent_message" or itype == "assistant_message":
                    text = item_text(item)
                    if text:
                        out({"type": "assistant", "message": {"role": "assistant",
                                                              "content": [{"type": "text", "text": text}]}})
                elif itype == "error":
                    # codex-cli 0.167 emits non-fatal items on every run
                    # (plugin-hook config, hook timeout). They are warnings:
                    # turn.failed is what ends a turn as failed.
                    warnings.append(item.get("message", "codex error item"))
                elif itype == "reasoning":
                    pass  # hidden from the chat
                # command_execution / file_change / mcp_tool_call are tool
                # activity of a full run; the text chat shows messages only.
            elif etype == "turn.completed":
                usage = ev.get("usage")
                turn_done = True
                break
            elif etype == "turn.failed":
                err = (ev.get("error") or {}).get("message", "turn failed")
                errors.append(err)
                turn_done = True
                break
            elif etype == "error":
                # Transport-level retry/noise; never ends a turn.
                warnings.append(ev.get("message", "codex error"))
    finally:
        with _state_lock:
            # A superseded reader (its process replaced by the next turn after
            # a timeout) must not report into the new turn.
            stale = _state["proc"] is not proc
            cancelled = _state["cancelled"]
        # EOF: the process ended before a terminal event.
        if not stale:
            if not turn_done:
                errors.append("cancelled by user" if cancelled
                              else "codex exited before completing the turn")
            # emit_result also owns the one-result-per-turn guard: a turn already
            # ended by the timeout path must not get a second result.
            emit_result(thread_id, bool(errors), "", errors + warnings, usage)


_turn_queue = queue.Queue()  # user messages; cancel/config handled inline


def stdin_loop():
    """stdin lives in its own thread: run_turn blocks the main loop while the
    turn runs, and the cancel the user sends must be acted on right then —
    a single-threaded reader deadlocks (same trap as in acp_bridge)."""
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
            with _state_lock:
                _state["config"] = {k: msg.get(k) for k in ("model", "effort", "resumeId", "contextFile")}
        elif mtype == "cancel":
            do_cancel()
        elif mtype == "user":
            _turn_queue.put(msg)
    _turn_queue.put(None)  # EOF


def stop_proc(proc, force=False):
    """Stop codex and everything it spawned (its own process group)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        try:
            proc.kill() if force else proc.terminate()
        except OSError:
            pass


def do_cancel():
    with _state_lock:
        proc = _state["proc"]
        done = _state["turn_done"]
        _state["cancelled"] = True
    if done:
        return
    stop_proc(proc)
    try:
        if proc is not None:
            proc.wait(timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        stop_proc(proc, force=True)
    # The reader will see EOF and emit the error result.


def run_turn(msg):
    with _state_lock:
        resume_id = _state["config"].get("resumeId", "")
        proc = _state["proc"]
        _state["turn_done"] = False
        _state["cancelled"] = False
    try:
        argv = build_argv(CMD, resume_id)
        text = canon_text(msg.get("message", {}).get("content"))
        try:
            ctx = load_context_text()
        except Exception as e:
            emit_result("", True, "", ["cannot read context file: %s" % e])
            return
        if ctx:
            text = ctx + text
        # Every turn is a fresh `codex exec`. A previous process that outlived
        # its turn (timeout) must be gone first: writing to its closed stdin
        # would fail the new turn and leave the old process running.
        if proc is not None and proc.poll() is None:
            stop_proc(proc, force=True)
            try:
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                pass
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=None,
                                text=True, bufsize=1, start_new_session=True)
        with _state_lock:
            _state["proc"] = proc
        t = threading.Thread(target=reader, args=(proc,), daemon=True)
        t.start()
        try:
            proc.stdin.write(text + "\n")
            proc.stdin.flush()
            proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            emit_result("", True, "", ["cannot write prompt: %s" % e])
            return
        # The reader thread emits the result; wait for the turn to end so the
        # next user message starts a new exec.
        deadline = time.monotonic() + float(os.environ.get("CODEX_TURN_TIMEOUT", "1800"))
        while time.monotonic() < deadline:
            with _state_lock:
                if _state["turn_done"]:
                    return
            time.sleep(0.1)
        # Claim the turn BEFORE the kill: the reader would otherwise see the
        # EOF first and report "exited before completing" instead of the real
        # cause. Then stop the child: a timed-out codex would otherwise keep
        # running with nobody reading it and poison the next turn.
        with _state_lock:
            if _state["turn_done"]:
                return
            _state["turn_done"] = True
        stop_proc(proc)
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            stop_proc(proc, force=True)
        send_result("", True, "", ["turn timed out"])
    except Exception as e:  # never leave the turn hanging
        emit_result("", True, "", ["bridge error: %s" % e])


CMD = None


def service_loop():
    while True:
        msg = _turn_queue.get()
        if msg is None:
            return
        run_turn(msg)


def _on_term(signum, frame):
    with _state_lock:
        proc = _state["proc"]
    stop_proc(proc)
    try:
        if proc is not None:
            proc.wait(timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        stop_proc(proc, force=True)
    sys.exit(0)


def main():
    global CMD
    if len(sys.argv) < 2:
        sys.stderr.write("usage: codex_bridge.py <codex-command...>\n")
        sys.exit(2)
    CMD = sys.argv[1:]
    # Stop in the chat SIGTERMs the bridge; the running codex (and its tools)
    # must go with it.
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    t = threading.Thread(target=stdin_loop, daemon=True)
    t.start()
    service_loop()


if __name__ == "__main__":
    main()
