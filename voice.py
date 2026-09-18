#!/usr/bin/env python3
"""Speech-to-text for DMS Agent's mic button, via local faster-whisper.

    voice.py transcribe <file.wav>   print {"text": ...} or {"error": ...} as JSON
    voice.py serve                   run the model server (started on demand)

Loading the model takes seconds, so it is kept in a small background server
that listens on a UNIX socket and exits on its own after IDLE_SECONDS without
requests. `transcribe` is the client: it starts the server when it is not
running and waits until the model is loaded. The client needs only the
standard library; the server runs in the whisper venv (install.sh creates it).

Configuration comes from the plugin settings via environment variables:
    DMS_AGENT_WHISPER_VENV    venv with faster-whisper
    DMS_AGENT_WHISPER_MODEL   "auto" (GPU: large-v3-turbo, CPU: small) or a model name
    DMS_AGENT_WHISPER_LANG    "auto" or a language code such as "en", "ru"
"""

import fcntl
import json
import os
import socket
import subprocess
import sys
import time

DEFAULT_VENV = "~/.local/share/dms-ai-agent/whisper-venv"
VENV = os.path.expanduser(os.environ.get("DMS_AGENT_WHISPER_VENV") or DEFAULT_VENV)
MODEL = os.environ.get("DMS_AGENT_WHISPER_MODEL") or "auto"
LANGUAGE = os.environ.get("DMS_AGENT_WHISPER_LANG") or "auto"
# Model picked for "auto": the large one is only fast enough on a GPU.
AUTO_GPU_MODEL = "large-v3-turbo"
AUTO_CPU_MODEL = "small"
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

def load_model(spec):
    from faster_whisper import WhisperModel
    try:
        name = AUTO_GPU_MODEL if spec == "auto" else spec
        return WhisperModel(name, device="cuda", compute_type="float16"), name
    except Exception as error:  # no GPU / CUDA libs: slower, but still works
        print(f"CUDA unavailable ({error}), falling back to CPU", file=sys.stderr, flush=True)
        name = AUTO_CPU_MODEL if spec == "auto" else spec
        return WhisperModel(name, device="cpu", compute_type="int8"), name


def serve():
    # MODEL is the setting this server was started with ("auto" or a name):
    # a request with another setting makes it step aside for a new server.
    model, loaded = load_model(MODEL)

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(4)
    server.settimeout(IDLE_SECONDS)
    print(f"ready: {loaded} (setting: {MODEL})", file=sys.stderr, flush=True)

    try:
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                print("idle timeout, exiting", file=sys.stderr, flush=True)
                return
            with conn:
                conn.settimeout(10)
                try:
                    request = json.loads(conn.makefile("r", encoding="utf-8").readline())
                except ValueError:
                    request = {}
                if request.get("model", MODEL) != MODEL:
                    conn.sendall(b'{"restart": true}\n')
                    print("model setting changed, exiting", file=sys.stderr, flush=True)
                    return
                result = transcribe_file(model, request.get("path", ""), request.get("language", "auto"))
                conn.sendall((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


def transcribe_file(model, path, language):
    if not path or not os.path.isfile(path):
        return {"error": f"no audio file: {path}"}
    try:
        segments, _ = model.transcribe(
            path,
            language=None if language in ("", "auto") else language,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return {"text": text}
    except Exception as error:
        return {"error": str(error)}


# --- client -------------------------------------------------------------------

class ServerRestarting(Exception):
    """The running server was started with another model setting and quit."""


def ask_server(path, timeout):
    request = {"path": path, "model": MODEL, "language": LANGUAGE}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(SOCKET_PATH)
        conn.sendall((json.dumps(request) + "\n").encode("utf-8"))
        reply = json.loads(conn.makefile("r", encoding="utf-8").readline())
    if reply.get("restart"):
        raise ServerRestarting()
    return reply


def start_server():
    python = os.path.join(VENV, "bin", "python")
    if not os.path.exists(python):
        raise RuntimeError(f"whisper venv not found: {VENV} (run install.sh or set the path in plugin settings)")
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
    except ServerRestarting:
        # Old server is on its way out; give it a moment to remove the socket.
        for _ in range(20):
            if not os.path.exists(SOCKET_PATH):
                break
            time.sleep(0.1)

    # Server is not running. The lock keeps two clicks from starting two servers.
    os.makedirs(RUNTIME, exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return ask_server(path, timeout=120)
        except (FileNotFoundError, ConnectionRefusedError, ServerRestarting):
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
