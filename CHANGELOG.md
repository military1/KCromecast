# Changelog

## 1.1.1 — 2026-10-23

- Add a one-command installer with dependency checks, panel setup, updates and uninstallation.
- Install the companion service independently of the download directory.
- Fix late snapshots and receiver callbacks after a service or network restart.
- Avoid blocking receiver callbacks while a sleep action waits for a response.
- Validate saved timers and discard deadlines older than two minutes.
- Handle revoked Spotify credentials and malformed API responses; reuse cached Spotify artwork.
- Add English and Russian documentation, screenshots, CI and release builds.

## 1.1.0 — 2026-10-23

- Add KDE media controls through MPRIS and event-driven widget updates.
- Add a persistent sleep timer with optional fade-out, track search and Spotify Connect setup.
- Improve reconnection, request timeouts and artwork caching.

## 1.0.1 — 2026-10-23

- Restore the mouse-control hint and add selectable track metadata.
- Select Russian for a Russian system language and English otherwise.

## 1.0.0 — 2026-10-23

- Initial KCromecast release: a compact Plasma 6 remote with artwork and a PyChromecast companion service.
