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
    // Key colors: { accent, panel, text, outline, neonFrom, neonTo }; absent = not set.
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
            outlineVariant: "#5a2a2e", error: "#ff2a3a",
            neon0: "#ff2a2a", neon1: "#e0102a", neon2: "#ff2a55", neon3: "#b5083a"
        },
        dark: {
            neon: false,
            primary: "#7aa2f7", primaryText: "#101014",
            surface: "#16161a", surfaceContainer: "#1e1e24", surfaceContainerHighest: "#2a2a32",
            surfaceVariant: "#34343d", surfaceText: "#e6e6ea", surfaceVariantText: "#9a9aa5",
            outlineVariant: "#44444e"
        },
        light: {
            neon: false, glass: false,
            primary: "#1f4fb0", primaryText: "#ffffff",
            surface: "#f6f6f8", surfaceContainer: "#ffffff", surfaceContainerHighest: "#ececf1",
            surfaceVariant: "#e0e0e8", surfaceText: "#1c1c20", surfaceVariantText: "#3a3a46",
            outlineVariant: "#c4c4ce", error: "#d32f2f"
        }
    })
    readonly property var presetIds: ["jarvis", "dms", "umbrella", "dark", "light"]

    readonly property var _preset: presets[preset] || presets.jarvis

    // The key colors stand for several roles each; the rest of a role group is derived so
    // that a light or dark choice stays readable.
    function _lum(c) { var k = Qt.color(c); return 0.2126 * k.r + 0.7152 * k.g + 0.0722 * k.b; }

    // Toward the opposite end of the lightness scale, e.g. a dark panel gets lighter.
    function _lift(c, t) { return _mix(c, _lum(c) < 0.5 ? "#ffffff" : "#000000", t); }

    function _fromCustom(name) {
        var c = custom || ({});
        switch (name) {
        case "primary": return c.accent;
        case "primaryText": return c.accent ? (_lum(c.accent) > 0.55 ? "#101014" : "#ffffff") : undefined;
        case "surfaceContainer": return c.panel;
        case "surfaceContainerHighest": return c.panel ? _lift(c.panel, 0.08) : undefined;
        case "surfaceVariant": return c.panel ? _lift(c.panel, 0.16) : undefined;
        case "surface": return c.panel ? _mix(c.panel, _lum(c.panel) < 0.5 ? "#000000" : "#ffffff", 0.3) : undefined;
        case "surfaceText": return c.text;
        case "surfaceVariantText": return c.text ? _mix(c.text, c.panel || (_preset.surfaceContainer || Theme.surfaceContainer), 0.35) : undefined;
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
    readonly property color error: pick("error", "#EF4444")
    readonly property color warning: pick("warning", "#FF9800")
    readonly property color onDark: pick("onDark", "#FFFFFF")

    readonly property bool neonEnabled: _preset.neon === true
    // Glass tints are made for dark backdrops; a light theme is drawn solid.
    readonly property bool glassAllowed: _preset.glass !== false
    readonly property color neon0: pick("neon0", "#3EE0FF")
    readonly property color neon1: pick("neon1", "#4F7BFF")
    readonly property color neon2: pick("neon2", "#9B5CFF")
    readonly property color neon3: pick("neon3", "#E14BFF")

    readonly property var roleNames: ["primary", "primaryText", "surface", "surfaceContainer",
        "surfaceContainerHighest", "surfaceVariant", "surfaceText", "surfaceVariantText",
        "outlineVariant", "error", "warning", "neon0", "neon1", "neon2", "neon3"]

    function _hex(v) { return typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v) ? v : ""; }

    // Colors are only read while their switch is on, so turning one off falls back to the theme.
    function apply(data) {
        preset = presets[data.themePreset] ? data.themePreset : "jarvis";
        var c = {};
        if (data.themeCustomOn === true) {
            var keys = ["accent", "panel", "text", "outline", "neonFrom", "neonTo"];
            for (var i = 0; i < keys.length; i++) {
                var v = _hex(data["themeColor_" + keys[i]]);
                if (v) c[keys[i]] = v;
            }
        }
        custom = c;
        var adv = {};
        if (data.themeAdvancedOn === true) {
            for (var j = 0; j < roleNames.length; j++) {
                var w = _hex(data["themeAdv_" + roleNames[j]]);
                if (w) adv[roleNames[j]] = w;
            }
        }
        advanced = adv;
    }
}
