.pragma library
.import "Translations.js" as Translations

// Only the first UI language counts. A secondary Russian fallback must never
// turn a German, Romanian or other non-Russian desktop into a Russian widget.
function languageFor(locale) {
    var languages = locale.uiLanguages || [];
    var primary = languages.length ? languages[0] : (locale.name || "en");
    return /^ru(?:[-_.@]|$)/i.test(primary) ? "ru" : "en";
}

function tr(locale, source) {
    var catalog = Translations.catalogs[languageFor(locale)];
    var text = Object.prototype.hasOwnProperty.call(catalog, source) ? catalog[source] : source;
    var args = arguments;
    return text.replace(/%([1-9][0-9]*)/g, function(match, index) {
        return Number(index) + 1 < args.length ? String(args[Number(index) + 1]) : match;
    });
}
