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
#
# The viewer registered for image/png is resolved and launched directly. That is
# the most portable of the three ways to do this: xdg-open is present everywhere
# but under niri it hangs without ever starting anything, and gio is not
# guaranteed to be installed. Both remain as fallbacks.
if [ "${1:-}" = "--open" ]; then
    file="${2:-}"
    [ -n "$file" ] || { echo "no-file"; exit 1; }

    cmd=$(python3 - "$file" <<'PY' 2>/dev/null
import os, shlex, subprocess, sys

desktop_id = ""
try:
    desktop_id = subprocess.run(
        ["xdg-mime", "query", "default", "image/png"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip()
except Exception:
    pass

if not desktop_id:
    sys.exit(1)

dirs = [os.path.expanduser("~/.local/share/applications")]
data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
dirs += [os.path.join(d, "applications") for d in data_dirs.split(":") if d]

path = next(
    (p for p in (os.path.join(d, desktop_id) for d in dirs) if os.path.isfile(p)),
    None,
)
if not path:
    sys.exit(1)

# Exec= of the first [Desktop Entry] group.
exec_line, in_entry = "", False
with open(path, encoding="utf-8", errors="replace") as fh:
    for raw in fh:
        line = raw.strip()
        if line.startswith("["):
            if in_entry:
                break
            in_entry = line == "[Desktop Entry]"
            continue
        if in_entry and line.startswith("Exec=") and not exec_line:
            exec_line = line[5:]

if not exec_line:
    sys.exit(1)

# Field codes (%f %F %u %U %i %c %k …) are dropped; the file is appended instead.
argv = [a for a in shlex.split(exec_line) if not (len(a) == 2 and a.startswith("%"))]
if not argv:
    sys.exit(1)

print(shlex.join(argv + [sys.argv[1]]))
PY
)

    if [ -n "$cmd" ]; then
        setsid sh -c "$cmd" >/dev/null 2>&1 &
    elif command -v gio >/dev/null 2>&1; then
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
