# Testing

[English README](../README.md) · [Описание на русском](../README.ru.md)

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
python3 scripts/translations.py
.venv/bin/python -m unittest discover -s tests -v
bash -n install.sh uninstall.sh
./install.sh --check
python3 scripts/build.py
```

`msgfmt` is needed to compile the translations. `dbus-run-session` enables the isolated MPRIS and event-stream integration tests. Qt tests are skipped when a Qt 6 QML runtime is not available.

In a Plasma development environment, also run:

```sh
qmllint -I /usr/lib/qt6/qml package/contents/ui/*.qml package/contents/config/config.qml
QT_QPA_PLATFORM=offscreen /usr/lib/qt6/bin/qmltestrunner -input tests/qml
```

Qt executable and import paths vary by distribution. Use the Qt 6 tools, not Qt 5 binaries with the same names.

## What is covered

- Cast transport commands, receiver capabilities and paused seeking.
- Reconnection, stale callbacks and malformed metadata.
- Event authentication, browser-origin rejection and a real Qt WebSocket client.
- MPRIS metadata, commands, seek protection and resume/network notifications in a private D-Bus session.
- Timer persistence, fading, cancellation, manual volume changes and expired deadlines.
- Spotify PKCE, callback state, token refresh, revoked access and API limits. These tests mock Spotify responses.
- Artwork resizing, cache limits and failed downloads.
- Russian/English selection, text copying, search URLs and stale snapshots.
- Installer helpers and release archive contents.

GitHub Actions runs the Python checks on Python 3.11, 3.13 and 3.14. QML rendering and hardware behavior are checked locally; passing Python CI alone does not certify a Plasma version or receiver.

## Hardware check

Tested on 23 October 2026 with KDE Plasma 6.8.1, Qt 6.12.0, Kirigami 6.31.0, Python 3.14.8 and Wayland. Two Technics SC-C30 speakers and their Google Cast group were discovered. Existing YouTube Music playback, metadata, artwork, volume, pause/resume and group reconnection were checked. A timer survived a service restart and was then cancelled.

Real Spotify Connect playback, a physical router outage, suspend/resume and Plasma 6.0 have not been tested on hardware. Spotify Cast and Spotify Connect should be reported separately when filing bugs.

## Release

`python3 scripts/build.py` creates a `.plasmoid`, a source ZIP and `SHA256SUMS` in `dist/`. The source archive uses an allowlist and contains no user settings or authentication files. Pushing a matching `vX.Y.Z` tag runs the release workflow after its tests pass.
