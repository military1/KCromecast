import QtQuick
import QtTest
import "../../package/contents/ui/TrackActions.js" as TrackActions

TestCase {
    name: "TrackActions"
    function test_search_escapes_metadata_and_uses_https() {
        var query = TrackActions.query("Исполнитель & Artist", "Track / #1?");
        compare(query, "Исполнитель & Artist — Track / #1?");
        compare(TrackActions.searchUrl("youtube_music", query), "https://music.youtube.com/search?q=" + encodeURIComponent(query));
        compare(TrackActions.searchUrl("spotify", query), "https://open.spotify.com/search/" + encodeURIComponent(query));
        compare(TrackActions.query("", "Track"), "Track");
    }
}
