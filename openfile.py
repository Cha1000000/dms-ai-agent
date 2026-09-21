#!/usr/bin/env python3
"""Open a file with whatever the desktop uses for its type.

xdg-open would be the obvious answer and is deliberately not used: under niri it
hangs without ever launching anything, so a click appears to do nothing. Instead
the handler registered for the file's type is resolved and started directly, and
when the type has no handler the portal is asked to show the "open with" chooser.
"""
import os
import shlex
import subprocess
import sys


def query(args):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5)
    except Exception:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def mime_of(path):
    mime = query(["xdg-mime", "query", "filetype", path])
    if mime:
        return mime
    # No xdg-utils: guess from the name, which is enough for common types.
    import mimetypes

    return mimetypes.guess_type(path)[0] or ""


def desktop_file(desktop_id):
    dirs = [os.path.expanduser("~/.local/share/applications")]
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs += [os.path.join(d, "applications") for d in data_dirs.split(":") if d]
    for d in dirs:
        candidate = os.path.join(d, desktop_id)
        if os.path.isfile(candidate):
            return candidate
    return ""


def exec_argv(path_to_desktop):
    """The Exec line of the first [Desktop Entry] group, field codes removed."""
    line, in_entry = "", False
    try:
        with open(path_to_desktop, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                stripped = raw.strip()
                if stripped.startswith("["):
                    if in_entry:
                        break
                    in_entry = stripped == "[Desktop Entry]"
                    continue
                if in_entry and stripped.startswith("Exec=") and not line:
                    line = stripped[5:]
    except OSError:
        return []

    if not line:
        return []
    return [a for a in shlex.split(line) if not (len(a) == 2 and a.startswith("%"))]


def launch(argv):
    try:
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def ask_portal(path):
    """Show the desktop's "open with" chooser. Needs the file as an fd."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    fd = os.open(path, os.O_RDONLY)
    try:
        fd_list = Gio.UnixFDList.new()
        handle = fd_list.append(fd)

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_with_unix_fd_list_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.OpenURI",
            "OpenFile",
            GLib.Variant("(sha{sv})", ("", handle, {"ask": GLib.Variant("b", True)})),
            GLib.VariantType("(o)"),
            Gio.DBusCallFlags.NONE,
            -1,
            fd_list,
            None,
        )
        return True
    finally:
        os.close(fd)


def main():
    if len(sys.argv) < 2:
        return 1
    path = sys.argv[1]
    if not os.path.exists(path):
        return 1

    desktop_id = query(["xdg-mime", "query", "default", mime_of(path)])
    if desktop_id:
        argv = exec_argv(desktop_file(desktop_id))
        if argv and launch(argv + [path]):
            return 0

    # Nothing is registered for this type — let the user choose.
    try:
        if ask_portal(path):
            return 0
    except Exception:
        pass

    if launch(["gio", "open", path]):
        return 0
    launch(["xdg-open", path])
    return 0


if __name__ == "__main__":
    sys.exit(main())
