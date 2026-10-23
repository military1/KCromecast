# KCromecast

**English** · [Русский](README.ru.md)

A Chromecast remote for the KDE Plasma panel. Start music on your phone, choose your speakers, and control playback from your desktop. Works alongside Firefox, Chrome or any other browser; no browser extension is needed.

![KCromecast playing YouTube Music](docs/screenshots/player.png)

## Install

Run this in a terminal inside **KDE Plasma 6**:

```sh
curl -fsSL https://raw.githubusercontent.com/military1/KCromecast/main/install.sh | bash
```

The installer checks requirements, installs missing packages on Arch-based systems, Debian/Ubuntu and Fedora, installs the widget and companion service for your user, and adds the widget to the panel. Administrator access is used only for missing system packages. Plasma panels are reloaded; open applications stay open.

You can also download the [latest release](https://github.com/military1/KCromecast/releases/latest), extract the **source ZIP**, and run `bash install.sh`. Installing the `.plasmoid` alone does **not** install the companion service.

Run the same command to update. Your settings and Spotify connection are kept. The download folder can be deleted after installation.

<details>
<summary>Installer options</summary>

```sh
bash install.sh --check                 # Check without changing anything
bash install.sh --no-system-packages    # Dependencies are already managed by your distro
bash install.sh --no-restart            # Load the new interface at your next login
bash install.sh --no-panel              # Add the widget yourself using Plasma's widget picker
```

Other distributions work when the required packages are installed. The installer does not upgrade a Plasma 5 desktop to Plasma 6.

</details>

## Features

- Control existing Google Cast sessions, including YouTube Music and Spotify Cast.
- Discover speakers and existing Google Home groups on your local network.
- Play/pause, previous/next track, seeking, volume and mute when the receiver supports them.
- Track title, artist, album and artwork; select and copy text or search for the track in your browser.
- Middle-click the panel icon to play/pause; scroll over it to adjust volume.
- KDE media controls and multimedia keys through MPRIS.
- Sleep timer with custom duration, optional fade-out and persistence across service restarts.
- Optional Spotify Connect control through the official Spotify Web API.
- Russian UI for a Russian system language; English for every other language.

Updates from Cast receivers are forwarded to the widget over a local event connection. Artwork is cached, and visual effects are inactive when the popup is closed.

<details>
<summary>More screenshots</summary>

![Playback menu](docs/screenshots/controls.png)
![Copying and searching for a track](docs/screenshots/track-menu.png)
![Paused playback](docs/screenshots/paused.png)

</details>

## Requirements and compatibility

| Component | Requirement |
| --- | --- |
| Desktop | KDE Plasma **6.0+**, within the Plasma 6 series |
| Qt | **6.6+**, including the QtWebSockets and QtQuick.Effects QML modules |
| Python | **3.11+** |
| Session | A running Plasma desktop and a working systemd user session |
| Network | Computer and Cast speakers on the same LAN, with mDNS allowed |

The current version has been tested on **Plasma 6.8.1, Qt 6.12.0 and Wayland**, with two Technics SC-C30 speakers and their Cast group. Plasma 6.0 / Qt 6.6 is the API baseline, not a claim that every intervening version has been tested. Plasma 5 and future major Plasma versions are not supported. Details and test commands are in [docs/TESTING.md](docs/TESTING.md).

The widget uses public Qt/KDE APIs and does not use Plasma5Support or `catt`. Blur and transparency depend on your Plasma theme and compositor. Ethernet on the computer and Wi-Fi on the speakers work together when the router allows local traffic.

## Spotify Connect

Spotify Cast works without signing in to KCromecast. For Spotify Connect, open **⋮ → Spotify Connect…**, create a personal app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), and enter its Client ID.

Add this exact redirect URI to the app:

```text
http://127.0.0.1:17844/spotify/callback
```

Click **Sign in with Spotify** and finish authorization in your browser. Your Connect devices will appear in the speaker list. Playing on an inactive Connect device transfers your account's current playback to it.

Playback control requires Spotify Premium and the app's user permissions. Spotify's [development-mode limits](https://developer.spotify.com/documentation/web-api/concepts/quota-modes) apply. Some devices do not expose remote volume or playback control. Tokens are stored locally with user-only permissions; the widget never asks for your password or Client Secret. Live Spotify Connect playback has not yet been verified with a signed-in account.

## Limits

This is a remote control, not an audio sender. It does not cast Firefox tabs, desktop audio or local files. Start a Cast session from a supported music app first. Group creation stays in Google Home. Available queue and seek commands depend on the active receiver app.

The sleep timer runs on the computer. It cannot pause speakers while the computer is off or asleep. An overdue timer gets a two-minute retry window; an older timer is discarded to avoid pausing a later session. Changing volume manually during a fade cancels that timer.

## Remove

```sh
bash ~/.local/share/kcromecast/uninstall.sh
```

Settings and backups are kept. Add `--purge` to remove them and the stored Spotify tokens. Standard XDG data/config/cache locations are respected.

For connection problems, use **⋮ → Reconnect speakers** and check:

```sh
journalctl --user -u kcromecast.service -n 50
```

[Report a bug](https://github.com/military1/KCromecast/issues) with your Plasma/Qt versions, speaker model and a short description of what happened.

## Development

See [docs/TESTING.md](docs/TESTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

GPL-3.0-or-later. Maintained by [military1](https://github.com/military1). Inspired by [KCast](https://github.com/Agundur-KDE/KCast) by Alec / Agundur. KDE, Google Cast and Spotify are trademarks of their respective owners.
