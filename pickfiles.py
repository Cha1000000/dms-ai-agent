#!/usr/bin/env python3
"""Ask the desktop for files to attach. Prints one absolute path per line.

The portal is tried first: it is what a browser opens for "choose a file", so
the dialog is the one the desktop already uses — GTK under GNOME-ish setups,
whatever is configured elsewhere. zenity and kdialog stand behind it for
systems without a portal.
"""
import os
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse

TITLE = "Attach to the agent"
TIMEOUT_SECONDS = 300


def via_portal():
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    picked = []

    # The reply arrives as a signal on a path the call returns, so the
    # subscription has to exist before the call is made.
    def on_response(_conn, _sender, path, _iface, _signal, params):
        if path != state.get("handle"):
            return
        response, results = params.unpack()
        if response == 0:
            picked.extend(results.get("uris", []))
        loop.quit()

    state = {}
    sub = bus.signal_subscribe(
        "org.freedesktop.portal.Desktop",
        "org.freedesktop.portal.Request",
        "Response",
        None, None, Gio.DBusSignalFlags.NONE,
        on_response,
    )

    token = "dmsagent{}".format(os.getpid())
    options = {
        "handle_token": GLib.Variant("s", token),
        "multiple": GLib.Variant("b", True),
        "modal": GLib.Variant("b", True),
    }

    reply = bus.call_sync(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.FileChooser",
        "OpenFile",
        GLib.Variant("(ssa{sv})", ("", TITLE, options)),
        GLib.VariantType("(o)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    state["handle"] = reply.unpack()[0]

    # A dialog nobody ever answers must not keep the process alive forever.
    GLib.timeout_add_seconds(TIMEOUT_SECONDS, lambda: (loop.quit(), False)[1])
    loop.run()
    bus.signal_unsubscribe(sub)

    paths = []
    for uri in picked:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            paths.append(unquote(parsed.path))
    return paths


def via_command(argv):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    out = result.stdout.strip()
    if not out:
        return []
    # zenity separates with |, kdialog with spaces around quoted names.
    return [p for p in out.replace("|", "\n").splitlines() if p]


def main():
    for attempt in (
        via_portal,
        lambda: via_command(["zenity", "--file-selection", "--multiple", "--separator=\n", "--title", TITLE])
        if shutil.which("zenity") else [],
        lambda: via_command(["kdialog", "--getopenfilename", os.path.expanduser("~"), "--multiple", "--separate-output", "--title", TITLE])
        if shutil.which("kdialog") else [],
    ):
        try:
            paths = attempt()
        except Exception:
            continue
        if paths:
            for p in paths:
                if os.path.isfile(p):
                    print(p)
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
