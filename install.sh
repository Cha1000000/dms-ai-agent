#!/usr/bin/env bash
# DMS AI Agent installer — works on Arch and Ubuntu/Debian (and most others).
#
#   curl -fsSL https://raw.githubusercontent.com/Cha1000000/dms-ai-agent/main/install.sh | bash
#   ./install.sh [options]
#
# Options:
#   --hotkey KEY        niri hotkey for the chat (default: Mod+Space; "none" to skip)
#   --no-voice          skip voice input setup (Python venv + Whisper model)
#   --voice-venv PATH   reuse an existing venv with faster-whisper instead of creating one
#   --no-model          do not pre-download the Whisper model (it downloads on first use)
#
# Safe to re-run: it updates the plugin in place and only adds what is missing.

set -euo pipefail

REPO_URL="https://github.com/Cha1000000/dms-ai-agent"
UPSTREAM_URL="https://github.com/Francisdelca/dms-agent"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
PLUGIN_DIR="$CONFIG_HOME/DankMaterialShell/plugins/dmsAgent"
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/dms-ai-agent/whisper-venv"
NIRI_CONFIG="$CONFIG_HOME/niri/config.kdl"
INCLUDE_LINE='include optional=true "dms-ai-agent.kdl"'

HOTKEY="Mod+Space"
WITH_VOICE=1
WITH_MODEL=1
REUSE_VENV=""

while [ $# -gt 0 ]; do
    case "$1" in
        --hotkey) HOTKEY="${2:?--hotkey needs a value}"; shift 2 ;;
        --no-voice) WITH_VOICE=0; shift ;;
        --voice-venv) REUSE_VENV="${2:?--voice-venv needs a path}"; shift 2 ;;
        --no-model) WITH_MODEL=0; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

DISTRO="$( (. /etc/os-release 2>/dev/null && echo "${ID_LIKE:-} ${ID:-}") || true)"
pkg_hint() {
    # $1 = Arch package, $2 = Debian/Ubuntu package
    case "$DISTRO" in
        *arch*) echo "sudo pacman -S $1" ;;
        *debian*|*ubuntu*) echo "sudo apt install $2" ;;
        *) echo "install '$1' with your package manager" ;;
    esac
}

# --- 1. Dependencies ------------------------------------------------------------
bold "Checking dependencies"
have git || fail "git is required: $(pkg_hint git git)"
have python3 || fail "python3 is required: $(pkg_hint python python3)"
have dms || fail "DankMaterialShell (dms) is not installed — see https://danklinux.com"
have claude && ok "claude CLI found" || warn "claude CLI not found — the agent needs it: https://docs.claude.com/en/docs/claude-code"
have notify-send || warn "notify-send missing (notifications): $(pkg_hint libnotify libnotify-bin)"
have niri || warn "niri not found — the hotkey and 'open on focused monitor' need niri; bind 'dms ipc call dmsAgent toggle' manually"
if [ "$WITH_VOICE" = 1 ] && ! have pw-record; then
    warn "pw-record missing (voice input needs PipeWire): $(pkg_hint pipewire pipewire-bin)"
fi

# --- 2. Plugin --------------------------------------------------------------------
bold "Installing the plugin"
mkdir -p "$(dirname "$PLUGIN_DIR")"
if [ -d "$PLUGIN_DIR/.git" ] && git -C "$PLUGIN_DIR" remote get-url origin 2>/dev/null | grep -q "Cha1000000/dms-ai-agent"; then
    git -C "$PLUGIN_DIR" pull --ff-only --quiet && ok "updated $PLUGIN_DIR"
else
    if [ -e "$PLUGIN_DIR" ]; then
        backup="$PLUGIN_DIR.backup-$(date +%Y%m%d-%H%M%S)"
        mv "$PLUGIN_DIR" "$backup"
        warn "existing plugin moved to $backup"
    fi
    git clone --quiet "$REPO_URL" "$PLUGIN_DIR" && ok "cloned into $PLUGIN_DIR"
fi
git -C "$PLUGIN_DIR" remote get-url upstream >/dev/null 2>&1 || git -C "$PLUGIN_DIR" remote add upstream "$UPSTREAM_URL"
chmod +x "$PLUGIN_DIR"/*.sh "$PLUGIN_DIR"/scripts/*.sh 2>/dev/null || true
mkdir -p "${XDG_STATE_HOME:-$HOME/.local/state}/dms-agent"

# DMS re-clones a plugin from the URL in its lockfile when a pull fails — make
# sure that URL is this fork, not the original plugin.
dms plugins lock >/dev/null 2>&1 && ok "DMS plugin lockfile updated" || warn "could not update the DMS plugin lockfile"

# --- 3. Voice input -------------------------------------------------------------
if [ "$WITH_VOICE" = 1 ]; then
    bold "Setting up voice input"
    if [ -n "$REUSE_VENV" ]; then
        [ -x "$REUSE_VENV/bin/python" ] || fail "no Python venv at $REUSE_VENV"
        mkdir -p "$(dirname "$VENV")"
        ln -sfn "$REUSE_VENV" "$VENV" && ok "using existing venv $REUSE_VENV"
    elif [ ! -x "$VENV/bin/python" ]; then
        mkdir -p "$(dirname "$VENV")"
        if have uv; then
            uv venv --quiet "$VENV"
        elif ! python3 -m venv "$VENV" 2>/dev/null; then
            rm -rf "$VENV"
            fail "python3 cannot create a venv: $(pkg_hint python python3-venv), then re-run"
        fi
        ok "created $VENV"
    fi

    pip_install() {
        if have uv; then uv pip install --quiet --python "$VENV/bin/python" "$@"
        else "$VENV/bin/python" -m pip install --quiet --upgrade "$@"; fi
    }

    GPU=0
    have nvidia-smi && nvidia-smi >/dev/null 2>&1 && GPU=1

    if [ -n "$REUSE_VENV" ]; then
        # Someone else's venv: check it, never install into it.
        "$VENV/bin/python" -c "import faster_whisper" 2>/dev/null \
            || fail "$REUSE_VENV has no faster-whisper — install it there or drop --voice-venv"
        ok "faster-whisper found in $REUSE_VENV"
    else
        pip_install faster-whisper || fail "could not install faster-whisper into $VENV"
        ok "faster-whisper installed"
        if [ "$GPU" = 1 ]; then
            # cuBLAS/cuDNN from pip: no system CUDA toolkit needed (voice.py sets LD_LIBRARY_PATH).
            if pip_install nvidia-cublas-cu12 nvidia-cudnn-cu12; then
                ok "CUDA libraries installed (NVIDIA GPU found)"
            else
                warn "CUDA libraries failed to install — recognition falls back to the CPU"
            fi
        else
            ok "no NVIDIA GPU — speech recognition will run on the CPU"
        fi
    fi

    if [ "$WITH_MODEL" = 1 ]; then
        model=$([ "$GPU" = 1 ] && echo large-v3-turbo || echo small)
        echo "  downloading Whisper model '$model' (one time)..."
        "$VENV/bin/python" -c "from faster_whisper import download_model; download_model('$model')" >/dev/null \
            && ok "model $model ready" || warn "model download failed — it will be retried on first use"
    fi
fi

# --- 4. Hotkey --------------------------------------------------------------------
if have niri && [ "$HOTKEY" != "none" ]; then
    bold "Setting the chat hotkey"
    if [ -f "$NIRI_CONFIG" ] && ! grep -qF "$INCLUDE_LINE" "$NIRI_CONFIG"; then
        cp -a "$NIRI_CONFIG" "$NIRI_CONFIG.backup-dms-ai-agent"
        printf '\n// DMS AI Agent chat hotkey (managed by the plugin) — keep this line last:\n// later binds override earlier ones with the same key.\n%s\n' "$INCLUDE_LINE" >> "$NIRI_CONFIG"
        if niri validate >/dev/null 2>&1; then
            ok "niri config includes dms-ai-agent.kdl (backup: $NIRI_CONFIG.backup-dms-ai-agent)"
        else
            mv "$NIRI_CONFIG.backup-dms-ai-agent" "$NIRI_CONFIG"
            warn "niri rejected the include — config restored; add manually: $INCLUDE_LINE"
        fi
    fi
    "$PLUGIN_DIR/keybind.sh" "$HOTKEY" >/dev/null && ok "hotkey $HOTKEY (change it in the plugin settings)" \
        || warn "hotkey $HOTKEY was not accepted by niri"
fi

# --- 5. Reload ----------------------------------------------------------------------
bold "Done"
if pgrep -x qs >/dev/null 2>&1 || pgrep -x quickshell >/dev/null 2>&1; then
    dms restart >/dev/null 2>&1 && ok "DMS restarted" || warn "restart DMS to load the plugin"
fi
cat <<EOF

Next steps in DMS:
  1. Settings → Plugins → enable "DMS AI Agent"
  2. Settings → Bar → add the "DMS AI Agent" widget where you want the pill
  3. Plugin settings: pill label, hotkey, Whisper model and language

Make sure the claude CLI is logged in (run 'claude' once in a terminal).
EOF
