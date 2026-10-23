import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import "Locale.js" as L10n
import "TrackActions.js" as TrackActions

QQC.TextArea {
    id: field
    property int maximumLines: 1
    property string trackTitle: ""
    property string trackArtist: ""
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
        QQC.MenuSeparator { visible: field.trackTitle.length > 0 }
        QQC.MenuItem {
            visible: field.trackTitle.length > 0
            text: L10n.tr(Qt.locale(), "Copy artist and title")
            icon.name: "edit-copy"
            onTriggered: {
                trackClipboard.text = TrackActions.query(field.trackArtist, field.trackTitle);
                trackClipboard.selectAll();
                trackClipboard.copy();
                trackClipboard.text = "";
            }
        }
        QQC.MenuItem {
            text: L10n.tr(Qt.locale(), "Search the web")
            icon.name: "internet-web-browser"
            enabled: field.text.length > 0
            onTriggered: Qt.openUrlExternally(TrackActions.searchUrl("web", field.selectedText || (field.trackTitle ? TrackActions.query(field.trackArtist, field.trackTitle) : field.text)))
        }
        QQC.MenuItem {
            visible: field.trackTitle.length > 0
            text: L10n.tr(Qt.locale(), "Find in YouTube Music")
            onTriggered: Qt.openUrlExternally(TrackActions.searchUrl("youtube_music", TrackActions.query(field.trackArtist, field.trackTitle)))
        }
        QQC.MenuItem {
            visible: field.trackTitle.length > 0
            text: L10n.tr(Qt.locale(), "Find in Spotify")
            onTriggered: Qt.openUrlExternally(TrackActions.searchUrl("spotify", TrackActions.query(field.trackArtist, field.trackTitle)))
        }
    }
    TextEdit { id: trackClipboard; visible: false }
}
