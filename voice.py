#!/usr/bin/env python3
"""Speech-to-text for DMS Agent's mic button, via local faster-whisper.

    voice.py transcribe <file.wav>   print {"text": ...} or {"error": ...} as JSON
    voice.py serve                   run the model server (started on demand)

Loading the model takes seconds, so it is kept in a small background server
that listens on a UNIX socket and exits on its own after IDLE_SECONDS without
requests. `transcribe` is the client: it starts the server when it is not
running and waits until the model is loaded. The client needs only the
standard library; the server runs in the whisper venv.
"""

import fcntl
import json
import os
import socket
import subprocess
import sys
import time

VENV = os.environ.get("DMS_AGENT_WHISPER_VENV", os.path.expanduser("~/mcp-servers/whisper-local/.venv"))
MODEL = os.environ.get("DMS_AGENT_WHISPER_MODEL", "large-v3-turbo")
LANGUAGE = os.environ.get("DMS_AGENT_WHISPER_LANG", "ru")
IDLE_SECONDS = int(os.environ.get("DMS_AGENT_WHISPER_IDLE", "600"))
STARTUP_TIMEOUT = 90

RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dms-agent-{os.getuid()}"
SOCKET_PATH = os.path.join(RUNTIME, "dms-agent-voice.sock")
LOCK_PATH = os.path.join(RUNTIME, "dms-agent-voice.lock")
LOG_PATH = os.path.join(RUNTIME, "dms-agent-voice.log")


def cuda_env():
    """The venv carries cuBLAS/cuDNN as pip packages; the loader only reads
    LD_LIBRARY_PATH at process start, so it is set for the server process."""
    env = dict(os.environ)
    nvidia = os.path.join(VENV, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages", "nvidia")
    if not os.path.isdir(nvidia):
        # The venv may use a different Python than the one running the client.
        lib = os.path.join(VENV, "lib")
        for name in sorted(os.listdir(lib)) if os.path.isdir(lib) else []:
            candidate = os.path.join(lib, name, "site-packages", "nvidia")
            if os.path.isdir(candidate):
                nvidia = candidate
                break
    paths = [os.path.join(nvidia, pkg, "lib") for pkg in ("cublas", "cudnn")]
    env["LD_LIBRARY_PATH"] = ":".join(paths + [env.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    return env


# --- server -------------------------------------------------------------------

def load_model():
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(MODEL, device="cuda", compute_type="float16")
    except Exception as error:  # no GPU / CUDA libs: slower, but still works
        print(f"CUDA unavailable ({error}), falling back to CPU", file=sys.stderr, flush=True)
        return WhisperModel(MODEL, device="cpu", compute_type="int8")


def serve():
    model = load_model()

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(4)
    server.settimeout(IDLE_SECONDS)
    print(f"ready: {MODEL}", file=sys.stderr, flush=True)

    try:
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                print("idle timeout, exiting", file=sys.stderr, flush=True)
                return
            with conn:
                conn.settimeout(10)
                path = conn.makefile("r", encoding="utf-8").readline().strip()
                conn.sendall((json.dumps(transcribe_file(model, path), ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


def transcribe_file(model, path):
    if not path or not os.path.isfile(path):
        return {"error": f"no audio file: {path}"}
    try:
        segments, _ = model.transcribe(
            path,
            language=LANGUAGE,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return {"text": text}
    except Exception as error:
        return {"error": str(error)}


# --- client -------------------------------------------------------------------

def ask_server(path, timeout):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(SOCKET_PATH)
        conn.sendall((path + "\n").encode("utf-8"))
        return json.loads(conn.makefile("r", encoding="utf-8").readline())


def start_server():
    python = os.path.join(VENV, "bin", "python")
    if not os.path.exists(python):
        raise RuntimeError(f"whisper venv not found: {VENV}")
    log = open(LOG_PATH, "a")
    subprocess.Popen(
        [python, os.path.abspath(__file__), "serve"],
        env=cuda_env(), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        start_new_session=True,
    )


def transcribe(path):
    path = os.path.abspath(path)
    try:
        return ask_server(path, timeout=120)
    except (FileNotFoundError, ConnectionRefusedError):
        pass

    # Server is not running. The lock keeps two clicks from starting two servers.
    os.makedirs(RUNTIME, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return ask_server(path, timeout=120)
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        start_server()
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                return ask_server(path, timeout=120)
            except (FileNotFoundError, ConnectionRefusedError):
                continue
    return {"error": f"speech server did not start, see {LOG_PATH}"}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "serve":
        serve()
    elif action == "transcribe" and len(sys.argv) > 2:
        try:
            result = transcribe(sys.argv[2])
        except Exception as error:
            result = {"error": str(error)}
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
