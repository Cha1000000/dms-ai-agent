import QtQuick
import QtQuick.Effects

// Neon gradient rim for a rounded card. A gradient plate slightly larger than
// the target peeks out around its edges as a ring, and a blurred copy of the
// plate underneath gives the glow. Must be a sibling of the target.
Item {
    id: neon

    property Item target
    property real radius: 20
    property real thickness: 2
    property real glowOpacity: 0.6

    visible: target ? target.visible : false
    z: target ? target.z - 1 : 0
    anchors.fill: target
    anchors.margins: -thickness

    Rectangle {
        id: rim
        anchors.fill: parent
        radius: neon.radius + neon.thickness
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#3EE0FF" }
            GradientStop { position: 0.35; color: "#4F7BFF" }
            GradientStop { position: 0.7; color: "#9B5CFF" }
            GradientStop { position: 1.0; color: "#E14BFF" }
        }
    }

    MultiEffect {
        source: rim
        anchors.fill: rim
        z: -1
        blurEnabled: true
        blurMax: 24
        blur: 1.0
        opacity: neon.glowOpacity
    }
}
