# Yoink

Yoink is an Omarchy bar plugin for downloading video and music from a small,
floating popup.

## Features

- Download YouTube videos or extract their audio with yt-dlp
- Download Spotify tracks, playlists, albums, and artist releases from Qobuz,
  Deezer, Tidal, or YouTube Music
- Search for songs by title through YouTube Music
- Choose the quality, output format, destination, metadata, and subtitles
- Prefer Qobuz, Deezer, or Tidal, with YouTube Music as the final fallback
- Keep downloads running when the popup closes and show progress on the bar icon
- Browse trending games, search titles, and view metadata from IGDB with Steam
  catalogue fallback
- Search the Books catalogue and optionally download from a source you provide

## Installation

```sh
omarchy pkg add streamrip python-ytmusicapi yt-dlp ffmpeg
git clone https://github.com/mxKeaton/yoink.git
cd yoink
./install.sh
```

Yoink appears as a download icon on the right side of the Omarchy bar. If it
does not appear immediately, run:

```sh
omarchy restart shell
```

## Setup

Open Yoink and select **Configuration** to connect the services you use:

- **Spotify:** [create a Spotify app](https://developer.spotify.com/dashboard/create),
  enter its client ID, and connect through the browser.
  Set `http://127.0.0.1:8765/callback` as the app's redirect URI.
- **Qobuz:** use either username/password or User ID, user auth token, App ID,
  and App Secret.
- **Deezer:** enter your account's ARL cookie.
- **Tidal:** connect through the browser or enter an existing session.
- **YouTube Music:** no account is required. A cookies file is optional.
- **Games:** optional IGDB/Twitch client ID and secret add richer catalogue
  metadata. Steam browsing works without credentials.

Credentials are stored locally in `~/.config/yoink/settings.json` with private
file permissions.

Book downloads use a separate source that you control. Add this to
`~/.config/yoink/settings.json` and adjust the URLs for your own site or local
HTTP stash:

```json
"book_download_source": {
  "base_url": "http://127.0.0.1:8080",
  "output_dir": "~/Downloads/Yoink/Books"
}
```

The search request uses the source's fixed `index.php?req=...` route. Search
result links should lead to a book page. Opaque entry links such as
`/ads.php?md5=...` are supported; the entry page should expose a download link
such as `GET`, `Download EPUB`, or a URL ending in `.pdf`, `.epub`, `.mobi`, or
another supported book format. You can set `detail_url` or `download_url`
templates when your site uses predictable paths; templates can use `{query}`,
`{title}`, `{author}`, `{id}`, `{md5}`, and `{extension}`.

## Usage

Paste a supported link or select **Search titles**. Choose the preferred source,
quality, and format, then press **Download**. Yoink tries other configured
sources when needed and uses YouTube Music last. Yoink automatically uses the
first result returned by each source.

Downloads are saved under `~/Downloads/Yoink` by default. Temporary artwork
is removed after covers are embedded into the audio files.

Use Yoink only to download media you are authorized to access and save.
Game download buttons are placeholders; Yoink only opens the related SteamDB
or Steam store page.
