import QtQuick
import QtTest
import "../../package/contents/ui/Locale.js" as L10n

TestCase {
    name: "Locale"

    function test_language_data() {
        return [
            {tag: "Russian", languages: ["ru-Cyrl-RU", "ru-RU"], name: "ru_RU", expected: "ru"},
            {tag: "Russian in Moldova", languages: ["ru-MD"], name: "ru_MD", expected: "ru"},
            {tag: "English", languages: ["en-US"], name: "en_US", expected: "en"},
            {tag: "Romanian", languages: ["ro-MD"], name: "ro_MD", expected: "en"},
            {tag: "German with Russian fallback", languages: ["de-DE", "ru-RU"], name: "de_DE", expected: "en"},
            {tag: "English UI with Russian formats", languages: ["en-US", "ru-RU"], name: "ru_RU", expected: "en"},
            {tag: "Russian UI with English formats", languages: ["ru-RU", "en-US"], name: "en_US", expected: "ru"},
            {tag: "Chinese", languages: ["zh-Hant-TW"], name: "zh_TW", expected: "en"},
            {tag: "C locale", languages: ["C"], name: "C", expected: "en"},
            {tag: "No UI preference", languages: [], name: "ru_RU.UTF-8", expected: "ru"},
            {tag: "No locale", languages: [], name: "", expected: "en"}
        ];
    }

    function test_language(data) {
        var locale = {uiLanguages: data.languages, name: data.name};
        compare(L10n.languageFor(locale), data.expected);
        compare(L10n.tr(locale, "Choose speakers"), data.expected === "ru" ? "Выбрать колонки" : "Choose speakers");
        compare(L10n.tr(locale, "Sleep in %1", "15:00"), data.expected === "ru" ? "Пауза через 15:00" : "Sleep in 15:00");
        compare(L10n.tr(locale, "Copy"), data.expected === "ru" ? "Копировать" : "Copy");
        compare(L10n.tr(locale, "Invalid volume"), data.expected === "ru" ? "Недопустимая громкость" : "Invalid volume");
    }

    function test_metadata_is_preserved() {
        compare(L10n.tr({uiLanguages: ["en"]}, "Unknown Track — Автор"), "Unknown Track — Автор");
        compare(L10n.tr({uiLanguages: ["ru"]}, "Sleep in %1", "Album %2"), "Пауза через Album %2");
    }
}
