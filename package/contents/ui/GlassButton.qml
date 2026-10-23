import QtQuick
import QtQuick.Controls as QQC
import org.kde.kirigami as Kirigami

QQC.AbstractButton {
    id: control
    property string glyph
    property string hint: text
    property bool prominent: false
    property bool quiet: false
    implicitWidth: prominent ? 64 : 40
    implicitHeight: implicitWidth
    padding: prominent ? 18 : 9
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : 0.3
    scale: down ? 0.93 : 1
    Accessible.name: hint
    Accessible.role: Accessible.Button

    Behavior on scale { NumberAnimation { duration: 100 } }
    Behavior on opacity { NumberAnimation { duration: 120 } }

    background: Rectangle {
        radius: height / 2
        color: control.prominent ? Kirigami.Theme.highlightColor
            : Qt.rgba(1, 1, 1, control.down ? 0.18 : control.hovered ? 0.12 : control.quiet ? 0 : 0.055)
        border.width: control.activeFocus || !control.quiet ? 1 : 0
        border.color: control.activeFocus ? Kirigami.Theme.highlightColor : Qt.rgba(1, 1, 1, 0.13)
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: parent.radius - 1
            visible: control.prominent
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.19) }
                GradientStop { position: 0.55; color: "transparent" }
            }
        }
    }
    contentItem: Kirigami.Icon {
        source: control.glyph
        implicitWidth: control.prominent ? 30 : 22
        implicitHeight: implicitWidth
        width: implicitWidth
        height: implicitHeight
        color: control.prominent ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
    }
    QQC.ToolTip.visible: hovered && hint.length > 0
    QQC.ToolTip.text: hint
    QQC.ToolTip.delay: 650
}
