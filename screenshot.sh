#!/usr/bin/env bash
# Screenshot of the focused window, written to $1.
#
# niri is the only thing here that can capture a single window: grim cannot
# (the compositor does not implement the screen capture protocol it wants),
# and grabbing the output instead would catch the chat itself, which floats
# above as a layer. niri always puts the shot on the clipboard and only
# optionally writes it to disk under whatever `screenshot-path` says — so the
# picture is taken from the clipboard, which needs no knowledge of that setting.
set -uo pipefail

# "--open FILE" shows a shot in the image viewer instead of taking one.
# xdg-open is not used first on purpose: under niri it hangs without ever
# starting the viewer, so the click appeared to do nothing at all.
if [ "${1:-}" = "--open" ]; then
    file="${2:-}"
    [ -n "$file" ] || { echo "no-file"; exit 1; }
    if command -v gio >/dev/null 2>&1; then
        setsid gio open "$file" >/dev/null 2>&1 &
    else
        setsid xdg-open "$file" >/dev/null 2>&1 &
    fi
    echo "ok"
    exit 0
fi

out="${1:-}"
[ -n "$out" ] || { echo "no-output-path"; exit 1; }

# Normally the window that has focus — the chat is a layer and does not take it
# away. When nothing is focused at all (the last window was closed, or the click
# landed on the desktop), fall back to whichever window held focus most recently.
id=$(niri msg -j windows 2>/dev/null \
    | python3 -c 'import json, sys
try:
    ws = json.load(sys.stdin) or []
except Exception:
    ws = []

focused = next((w for w in ws if w.get("is_focused")), None)
if focused is None:
    def stamp(w):
        t = w.get("focus_timestamp") or {}
        return (t.get("secs", 0), t.get("nanos", 0))
    focused = max(ws, key=stamp) if ws else None

print(focused["id"] if focused else "")' 2>/dev/null)

[ -n "$id" ] || { echo "no-window"; exit 1; }

niri msg action screenshot-window --id "$id" -d false >/dev/null 2>&1 || {
    echo "screenshot-failed"; exit 1
}

# The clipboard is served by niri asynchronously; a moment is needed before it
# answers with the image.
sleep 0.4
wl-paste --type image/png > "$out" 2>/dev/null

[ -s "$out" ] || { rm -f "$out"; echo "empty"; exit 1; }
echo "ok"
