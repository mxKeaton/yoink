# Yoinker

Yoinker is an Omarchy bar plugin for downloading video and music from a small,
floating popup.

## Features

- Download YouTube videos or extract their audio with yt-dlp
- Download Spotify tracks, playlists, albums, and artist releases from Qobuz,
  Deezer, Tidal, or YouTube Music
- Search for songs by title through YouTube Music
- Choose the quality, output format, destination, metadata, and subtitles
- Prefer Qobuz, Deezer, or Tidal, with YouTube Music as the final fallback
- Keep downloads running when the popup closes and show progress on the bar icon

## Installation

```sh
omarchy pkg add streamrip python-ytmusicapi yt-dlp ffmpeg
git clone https://github.com/mxKeaton/yoinker.git
cd yoinker
./install.sh
```

Yoinker appears as a download icon on the right side of the Omarchy bar. If it
does not appear immediately, run:

```sh
omarchy restart shell
```

## Setup

Open Yoinker and select **Configuration** to connect the services you use:

- **Spotify:** [create a Spotify app](https://developer.spotify.com/dashboard/create),
  enter its client ID, and connect through the browser.
  Set `http://127.0.0.1:8765/callback` as the app's redirect URI.
- **Qobuz:** use either username/password or User ID, user auth token, App ID,
  and App Secret.
- **Deezer:** enter your account's ARL cookie.
- **Tidal:** connect through the browser or enter an existing session.
- **YouTube Music:** no account is required. A cookies file is optional.

Credentials are stored locally in `~/.config/yoinker/settings.json` with private
file permissions.

## Usage

Paste a supported link or select **Search titles**. Choose the preferred source,
quality, and format, then press **Download**. Yoinker tries other configured
sources when needed and uses YouTube Music last. Yoinker automatically uses the
first result returned by each source.

Downloads are saved under `~/Downloads/Yoinker` by default. Temporary artwork
is removed after covers are embedded into the audio files.

Use Yoinker only to download media you are authorized to access and save.
