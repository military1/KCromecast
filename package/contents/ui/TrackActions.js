.pragma library

function query(artist, title) {
    return [String(artist || "").trim(), String(title || "").trim()].filter(function(part) { return part.length > 0; }).join(" — ");
}

function searchUrl(provider, text) {
    var encoded = encodeURIComponent(text);
    if (provider === "youtube_music") return "https://music.youtube.com/search?q=" + encoded;
    if (provider === "spotify") return "https://open.spotify.com/search/" + encoded;
    return "https://www.google.com/search?q=" + encoded;
}
