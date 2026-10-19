pragma Singleton

import QtQuick
import Quickshell
import qs.Common

// Colors of the chat window. Every role defaults to the DMS theme; a preset, the
// key colors from the settings and the advanced per-role overrides are layered on
// top of it, later ones winning.
Singleton {
    id: root

    property string preset: "jarvis"
    // Key colors: { accent, panel, text, outline, neonFrom, neonTo }; "" = not set.
    property var custom: ({})
    // Per-role overrides of the advanced editor: { role: "#rrggbb" }.
    property var advanced: ({})

    readonly property var presets: ({
        jarvis: { neon: true },
        dms: { neon: false },
        umbrella: {
            neon: true,
            primary: "#b8101a", primaryText: "#ffffff",
            surface: "#140607", surfaceContainer: "#1c0a0c", surfaceContainerHighest: "#2a1013",
            surfaceVariant: "#2e1215", surfaceText: "#f2e6e6", surfaceVariantText: "#b59a9c",
            outlineVariant: "#5a2a2e",
            neon0: "#ff3b3b", neon1: "#b8101a", neon2: "#ff6a3d", neon3: "#ffb347"
        },
        dark: {
            neon: false,
            primary: "#7aa2f7", primaryText: "#101014",
            surface: "#16161a", surfaceContainer: "#1e1e24", surfaceContainerHighest: "#2a2a32",
            surfaceVariant: "#34343d", surfaceText: "#e6e6ea", surfaceVariantText: "#9a9aa5",
            outlineVariant: "#44444e"
        },
        light: {
            neon: false,
            primary: "#3b6fd4", primaryText: "#ffffff",
            surface: "#f6f6f8", surfaceContainer: "#ffffff", surfaceContainerHighest: "#ececf1",
            surfaceVariant: "#e0e0e8", surfaceText: "#1c1c20", surfaceVariantText: "#5c5c68",
            outlineVariant: "#c4c4ce"
        }
    })
    readonly property var presetIds: ["jarvis", "dms", "umbrella", "dark", "light"]

    readonly property var _preset: presets[preset] || presets.jarvis

    // The key colors stand for several roles each.
    function _fromCustom(name) {
        var c = custom || ({});
        switch (name) {
        case "primary": return c.accent;
        case "surfaceContainer": return c.panel;
        case "surfaceContainerHighest": return c.panel ? Qt.lighter(c.panel, 1.2) : undefined;
        case "surfaceText": return c.text;
        case "outlineVariant": return c.outline;
        case "neon0": return c.neonFrom;
        case "neon3": return c.neonTo;
        case "neon1": return _mix(c.neonFrom, c.neonTo, 0.35);
        case "neon2": return _mix(c.neonFrom, c.neonTo, 0.7);
        }
        return undefined;
    }

    function _mix(from, to, t) {
        if (!from || !to) return undefined;
        var a = Qt.color(from), b = Qt.color(to);
        return Qt.rgba(a.r + (b.r - a.r) * t, a.g + (b.g - a.g) * t, a.b + (b.b - a.b) * t, 1);
    }

    function pick(name, dmsValue) {
        var v = (advanced || ({}))[name];
        if (!v) v = _fromCustom(name);
        if (!v) v = _preset[name];
        return v ? v : dmsValue;
    }

    readonly property color primary: pick("primary", Theme.primary)
    readonly property color primaryText: pick("primaryText", Theme.primaryText || "#FFFFFF")
    readonly property color surface: pick("surface", Theme.surface)
    readonly property color surfaceContainer: pick("surfaceContainer", Theme.surfaceContainer)
    readonly property color surfaceContainerHighest: pick("surfaceContainerHighest", Theme.surfaceContainerHighest)
    readonly property color surfaceVariant: pick("surfaceVariant", Theme.surfaceVariant)
    readonly property color surfaceText: pick("surfaceText", Theme.surfaceText)
    readonly property color surfaceVariantText: pick("surfaceVariantText", Theme.surfaceVariantText)
    readonly property color outlineVariant: pick("outlineVariant", Theme.outlineVariant)
    readonly property color shadow: pick("shadow", Theme.shadow || "#000000")
    readonly property color error: pick("error", Theme.error || "#EF4444")
    readonly property color warning: pick("warning", "#FF9800")
    readonly property color onDark: pick("onDark", "#FFFFFF")

    readonly property bool neonEnabled: _preset.neon === true
    readonly property color neon0: pick("neon0", "#3EE0FF")
    readonly property color neon1: pick("neon1", "#4F7BFF")
    readonly property color neon2: pick("neon2", "#9B5CFF")
    readonly property color neon3: pick("neon3", "#E14BFF")

    // The settings come as plain strings; "" and bad values mean "not set".
    function apply(data) {
        var id = data.themePreset;
        preset = presets[id] ? id : "jarvis";
        var keys = ["accent", "panel", "text", "outline", "neonFrom", "neonTo"];
        var c = {};
        for (var i = 0; i < keys.length; i++) {
            var v = data["themeColor_" + keys[i]];
            if (typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v)) c[keys[i]] = v;
        }
        custom = c;
        var adv = data.themeAdvanced;
        if (typeof adv === "string") { try { adv = JSON.parse(adv); } catch (e) { adv = ({}); } }
        advanced = (adv && typeof adv === "object") ? adv : ({});
    }
}
