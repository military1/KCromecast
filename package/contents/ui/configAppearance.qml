import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

KCM.SimpleKCM {
    property real cfg_glassOpacity
    property bool cfg_reduceMotion

    Kirigami.FormLayout {
        QQC.Slider {
            Kirigami.FormData.label: i18n("Surface opacity:")
            from: 0.4
            to: 1
            stepSize: 0.02
            value: cfg_glassOpacity
            onMoved: cfg_glassOpacity = value
        }
        QQC.CheckBox {
            text: i18n("Reduce animations")
            checked: cfg_reduceMotion
            onToggled: cfg_reduceMotion = checked
        }
        QQC.Label {
            Layout.maximumWidth: 360
            text: i18n("Colours and fonts follow your Plasma theme. Background blur follows your desktop's transparency settings.")
            wrapMode: Text.WordWrap
        }
    }
}
