import QtQuick
import Quickshell
import Quickshell.Wayland

// Liquid glass: one blur patch per bubble of `chat` over the part of it inside
// the feed, rounded like the bubble. A compositor with a glass
// shader (Lniri) draws a lens per patch; plain niri just blurs them.
//
// Loaded only while the mode is on, so a Quickshell without background effects
// costs nothing but this file, and turning the mode off drops the region.
Item {
    id: glass

    required property var targetWindow
    required property var chat
    // The patches go with the chat: off as soon as it starts to fade out,
    // rather than lingering sharp while the bubbles disappear.
    property bool shown: true
    property real lensScale: 1

    visible: false

    Variants {
        id: patches
        model: glass.chat.glassItems

        Region {
            id: patch
            required property var modelData
            readonly property rect area: { glass.chat.glassTick; return glass.chat.glassRect(modelData); }
            x: area.x; y: area.y; width: area.width; height: area.height
            // Rounded like the bubble's tint (GlassTint), which shrinks the radius
            // for a sliver left at the edge of the feed.
            radius: Math.min((modelData ? modelData.radius : 0) * glass.lensScale, area.height / 2)
        }
    }
    Region { id: region; regions: patches.instances }

    // Republished the way DMS's own WindowBlur does it: a region change is not
    // always picked up by the compositor on its own (after a remap, for one).
    // At most once a frame while things move, plus a trailing pass once they settle.
    function apply() {
        if (!targetWindow) return;
        targetWindow.BackgroundEffect.blurRegion = null;
        if (shown && armed && targetWindow.visible) targetWindow.BackgroundEffect.blurRegion = region;
    }
    function kick() {
        if (!frameTimer.running) frameTimer.start();
        settleTimer.restart();
    }
    Timer { id: frameTimer; interval: 16; onTriggered: glass.apply() }
    Timer { id: settleTimer; interval: 96; onTriggered: glass.apply() }

    // The chat fades in over ~200 ms. Blur appearing before the bubbles would show
    // as bare blurred rectangles, so it starts once they are mostly there.
    property bool armed: false
    Timer { id: armTimer; interval: 150; onTriggered: { glass.armed = true; glass.kick(); } }
    onShownChanged: {
        if (shown) armTimer.restart();
        else { armTimer.stop(); armed = false; apply(); }
    }
    onLensScaleChanged: chat.bumpGlass()
    Connections {
        target: glass.chat
        function onGlassTickChanged() { glass.kick(); }
        function onGlassItemsChanged() { glass.kick(); }
    }
    Connections {
        target: glass.targetWindow
        ignoreUnknownSignals: true
        function onVisibleChanged() { glass.kick(); }
        function onWidthChanged() { glass.chat.bumpGlass(); }
        function onHeightChanged() { glass.chat.bumpGlass(); }
        function onWindowConnected() { glass.kick(); }
        function onResourcesLost() { glass.kick(); }
    }

    Component.onCompleted: if (shown) armTimer.start()
    Component.onDestruction: {
        if (targetWindow) targetWindow.BackgroundEffect.blurRegion = null;
    }
}
