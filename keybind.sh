#!/usr/bin/env bash
# Writes the chat hotkey into a small niri config file owned by this plugin.
#
#   keybind.sh "Mod+Space"   bind the key to toggle the chat
#   keybind.sh ""            remove the binding
#
# The file is included at the very end of ~/.config/niri/config.kdl
# (install.sh adds `include optional=true "dms-ai-agent.kdl"`). niri lets later
# binds override earlier ones with the same key, so this binding wins over the
# DMS defaults, and niri reloads included files on its own.
#
# The candidate is validated on its own before it replaces the live file, so a
# typo in the settings never breaks the running niri config.

set -u

KEY="${1-}"
NIRI_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/niri"
TARGET="$NIRI_DIR/dms-ai-agent.kdl"
INCLUDE_LINE='include optional=true "dms-ai-agent.kdl"'

if ! command -v niri >/dev/null 2>&1; then
    echo "niri not found: bind 'dms ipc call dmsAgent toggle' in your compositor manually" >&2
    exit 2
fi

KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
case "$KEY" in
    *'"'* | *'{'* | *'}'* | *';'*) echo "invalid key: $KEY" >&2; exit 1 ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

{
    echo "// Managed by the DMS AI Agent plugin — change the hotkey in"
    echo "// DMS Settings → Plugins → DMS AI Agent instead of editing this file."
    echo "binds {"
    if [ -n "$KEY" ]; then
        echo "    $KEY hotkey-overlay-title=\"AI Agent chat\" { spawn \"dms\" \"ipc\" \"call\" \"dmsAgent\" \"toggle\"; }"
    fi
    echo "}"
} > "$tmp/dms-ai-agent.kdl"

if [ -f "$TARGET" ] && cmp -s "$tmp/dms-ai-agent.kdl" "$TARGET"; then
    exit 0
fi

printf 'include "%s"\n' "$tmp/dms-ai-agent.kdl" > "$tmp/check.kdl"
if ! error="$(niri validate -c "$tmp/check.kdl" 2>&1)"; then
    echo "niri rejected key '$KEY':" >&2
    printf '%s\n' "$error" | grep -vE 'DEBUG|INFO' | tail -5 >&2
    exit 1
fi

mkdir -p "$NIRI_DIR"
mv "$tmp/dms-ai-agent.kdl" "$TARGET"

if [ -f "$NIRI_DIR/config.kdl" ] && ! grep -qF "$INCLUDE_LINE" "$NIRI_DIR/config.kdl"; then
    echo "note: $NIRI_DIR/config.kdl does not include dms-ai-agent.kdl yet;" >&2
    echo "      add this line at the end of it: $INCLUDE_LINE" >&2
fi
echo "hotkey: ${KEY:-none}"
