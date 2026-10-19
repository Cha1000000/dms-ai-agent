import QtQuick
import QtQuick.Effects

// Neon gradient rim for a rounded card. Must be a sibling of the target.
//
// Solid cards: a gradient plate slightly larger than the target peeks out
// around its edges as a ring, and a blurred copy of the plate underneath gives
// the glow. A translucent card would show the whole plate through itself, so
// with `ring` set only the outline is drawn: it is softened and brightened a
// little, and its blurred copy gives the glow.
Item {
    id: neon

    property Item target
    property real radius: 20
    property real thickness: 2
    property real glowOpacity: 0.6
    property bool ring: false

    visible: target ? target.visible && AgentTheme.neonEnabled : false
    z: target ? target.z - 1 : 0
    anchors.fill: target
    anchors.margins: -thickness

    Rectangle {
        id: rim
        visible: !neon.ring
        anchors.fill: parent
        radius: neon.radius + neon.thickness
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: AgentTheme.neon0 }
            GradientStop { position: 0.35; color: AgentTheme.neon1 }
            GradientStop { position: 0.7; color: AgentTheme.neon2 }
            GradientStop { position: 1.0; color: AgentTheme.neon3 }
        }
    }

    MultiEffect {
        visible: !neon.ring
        source: rim
        anchors.fill: rim
        z: -1
        blurEnabled: true
        blurMax: 24
        blur: 1.0
        opacity: neon.glowOpacity
    }

    // The ring variant: only built while it is in use, so the default look costs nothing extra.
    Loader {
        active: neon.ring
        anchors.fill: parent
        sourceComponent: Item {
            // Painted into a texture only; what is shown are the two effects below.
            Canvas {
                id: ringCanvas
                visible: false
                anchors.fill: parent

                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: neon
                    function onRadiusChanged() { ringCanvas.requestPaint(); }
                    function onThicknessChanged() { ringCanvas.requestPaint(); }
                }
                Connections {
                    target: AgentTheme
                    function onNeon0Changed() { ringCanvas.requestPaint(); }
                    function onNeon1Changed() { ringCanvas.requestPaint(); }
                    function onNeon2Changed() { ringCanvas.requestPaint(); }
                    function onNeon3Changed() { ringCanvas.requestPaint(); }
                }

                onPaint: {
                    var c = getContext("2d");
                    c.reset();
                    var t = neon.thickness, r = neon.radius + t / 2;
                    var g = c.createLinearGradient(0, 0, width, 0);
                    g.addColorStop(0.0, AgentTheme.neon0);
                    g.addColorStop(0.35, AgentTheme.neon1);
                    g.addColorStop(0.7, AgentTheme.neon2);
                    g.addColorStop(1.0, AgentTheme.neon3);
                    c.strokeStyle = g;
                    c.lineWidth = t;
                    c.beginPath();
                    c.roundedRect(t / 2, t / 2, width - t, height - t, r, r);
                    c.stroke();
                }
            }

            MultiEffect {
                source: ringCanvas
                anchors.fill: ringCanvas
                blurEnabled: true
                blurMax: 20
                blur: 1.0
                saturation: 0.6
                brightness: 0.2
            }

            MultiEffect {
                source: ringCanvas
                anchors.fill: ringCanvas
                z: -1
                blurEnabled: true
                blurMax: 24
                blur: 1.0
                brightness: 0.4
                opacity: 0.5
            }
        }
    }
}
