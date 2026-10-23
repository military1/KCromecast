## English

Chromecast remote for KDE Plasma 6: playback controls, artwork, speaker groups, KDE media keys, a sleep timer and optional Spotify Connect.

This release fixes restart ordering, expired sleep timers, stale receiver updates and Spotify sign-in handling. The installer now checks dependencies, installs a standalone companion service, configures the panel and reloads it. Deleting the download folder no longer breaks the service.

**Requirements:** Plasma 6.0+ in the Plasma 6 series, Qt 6.6+, Python 3.11+ and a systemd user session. Tested on Plasma 6.8.1 / Qt 6.12.0 / Wayland with Technics SC-C30 speakers. Older Plasma 6 versions are an API target, not a tested matrix.

**Install:** download the source ZIP, extract it, and run `bash install.sh`, or use the one-command installer in the README. The `.plasmoid` alone needs the companion service.

[English README](https://github.com/military1/KCromecast#readme)

## Русский

Пульт Chromecast для KDE Plasma 6: управление воспроизведением, обложки, группы колонок, системные клавиши KDE, таймер сна и дополнительное подключение Spotify Connect.

Исправлены порядок обновлений при перезапуске, просроченные таймеры, устаревшие события от колонок и обработка входа Spotify. Установщик проверяет зависимости, устанавливает независимую фоновую службу, добавляет виджет в панель и перезагружает её. Удаление папки с исходниками больше не ломает службу.

**Требования:** Plasma 6.0+ в пределах ветки 6, Qt 6.6+, Python 3.11+ и пользовательский systemd. Проверено на Plasma 6.8.1 / Qt 6.12.0 / Wayland с Technics SC-C30. Более ранние версии Plasma 6 — целевой уровень API, а не проверенная матрица.

**Установка:** распакуйте архив исходников и выполните `bash install.sh` либо используйте одну команду из README. Одному файлу `.plasmoid` нужна отдельно установленная фоновая служба.

[Описание на русском](https://github.com/military1/KCromecast/blob/main/README.ru.md)
