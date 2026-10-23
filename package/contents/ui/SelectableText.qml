import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import "Locale.js" as L10n

QQC.TextArea {
    id: field
    property int maximumLines: 1
    readonly property real lineHeight: metrics.lineSpacing
    Layout.fillWidth: true
    implicitHeight: Math.min(contentHeight, Math.ceil(lineHeight * maximumLines))
    readOnly: true
    selectByMouse: true
    persistentSelection: true
    wrapMode: TextEdit.Wrap
    clip: true
    padding: 0
    background: null
    color: Kirigami.Theme.textColor
    selectionColor: Kirigami.Theme.highlightColor
    selectedTextColor: Kirigami.Theme.highlightedTextColor
    activeFocusOnTab: true
    FontMetrics { id: metrics; font: field.font }

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: contextMenu.popup()
    }
    QQC.Menu {
        id: contextMenu
        QQC.MenuItem {
            text: L10n.tr(Qt.locale(), "Copy")
            icon.name: "edit-copy"
            enabled: field.text.length > 0
            onTriggered: {
                if (!field.selectedText.length) field.selectAll();
                field.copy();
            }
        }
        QQC.MenuItem {
            text: L10n.tr(Qt.locale(), "Select all")
            icon.name: "edit-select-all"
            enabled: field.text.length > 0
            onTriggered: { field.forceActiveFocus(); field.selectAll(); }
        }
    }
}
