import QtQuick
import QtTest
import "../../package/contents/ui"

TestCase {
    id: testCase
    name: "SelectableText"
    when: windowShown
    width: 360
    height: 160

    SelectableText {
        id: title
        width: 180
        text: "Long track title — Длинное название трека"
        maximumLines: 2
        font.pixelSize: 16
    }
    TextEdit { id: clipboardTarget; y: 80; width: 300; height: 60 }

    function cleanup() {
        title.deselect();
        clipboardTarget.text = "";
    }

    function test_copy_with_keyboard() {
        title.forceActiveFocus();
        keyClick(Qt.Key_A, Qt.ControlModifier);
        compare(title.selectedText, title.text);
        keyClick(Qt.Key_C, Qt.ControlModifier);
        clipboardTarget.forceActiveFocus();
        keyClick(Qt.Key_V, Qt.ControlModifier);
        compare(clipboardTarget.text, title.text);
    }

    function test_read_only_and_compact() {
        title.forceActiveFocus();
        title.selectAll();
        keyClick(Qt.Key_Delete);
        compare(title.text, "Long track title — Длинное название трека");
        verify(title.selectByMouse);
        verify(title.height <= Math.ceil(title.lineHeight * 2));
    }
}
