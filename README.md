# Yoinker

An Omarchy bar popup for direct media downloads. Paste a YouTube link to download
video/audio, or a Spotify song/playlist/album/artist link to match and download music from
Qobuz, Deezer, Tidal, or YouTube Music.

## Install / update

```sh
omarchy pkg add streamrip python-ytmusicapi yt-dlp ffmpeg
./install.sh
```

The installer copies runtime files into `~/.config/omarchy/plugins/denis.yoinker`,
enables the icon on the right, and disables the former `denis.media-downloader`
widget. It retains that old installation and backs up subsequent Yoinker updates
under `~/.local/state/yoinker/backups/`. Files hot-reload; if Omarchy retains a stale
widget, run `omarchy restart shell`.

The popup uses `/usr/bin/python` so it can access the Arch-installed streamrip
and ytmusicapi packages even when a separate Python from mise is on PATH.
Tested against installed streamrip 2.2.0. It uses the library's configuration,
clients, metadata, download, tagging, and conversion APIs.

## Configure accounts

Click **Configuration** inside the popup. Credentials are sent to the helper over
stdin, never command-line arguments. Settings live in
`$XDG_CONFIG_HOME/yoinker/settings.json` (normally `~/.config/yoinker/settings.json`),
with directory mode 700 and file mode 600. This is a private local file, **not an
encrypted keyring**. Secret fields show only whether a value is saved; leaving one
blank preserves it. **Forget this platform** removes its saved credentials.

- **Spotify:** create your own app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard),
  register `http://127.0.0.1:8765/callback`, save its client ID, then click
  **Connect Spotify**. Authorization happens in your browser via PKCE. Refresh
  tokens are stored locally. Spotify is used for metadata, not audio downloads.
- **Qobuz:** choose **Username / Password** or **User ID / App ID / App Secret**.
  The second mode also requires your **user auth token**: app credentials alone
  cannot authenticate an account. Saved credentials from the other mode are
  retained, but only the selected mode is used. App ID/Secret are passed directly
  to streamrip; when omitted, streamrip discovers its app credentials. Passwords are stored as the MD5 hash required
  by streamrip's Qobuz login, rather than plaintext.
- **Deezer:** enter your account's ARL cookie. No shared-account/deezloader fallback
  is enabled. See [streamrip's ARL guide](https://github.com/nathom/streamrip/wiki/Finding-Your-Deezer-ARL-Cookie).
- **Tidal:** click **Connect Tidal** for browser device authorization, or enter an
  existing user ID, country code, access/refresh tokens, and Unix expiry time.
  Streamrip refreshes existing sessions as needed.
- **YouTube Music:** catalog search needs no account. Optionally provide a path
  to your own Netscape-format cookies file for downloading matched tracks.

Spotify app/account restrictions still apply. In particular, development-mode
apps have restricted playlist access; private/shared playlists must be accessible
to the authorized user. See the [2026 Spotify API migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
An account's subscription, region, and catalog determine which recordings and
qualities are available on each download source.

## Spotify downloads

Paste a full `open.spotify.com/track/...` , `/playlist/...`, `/album/...`, or `/artist/...` link (Spotify URIs and
localized links also work). Album tracks are paginated in release order. Artist
links collect albums and singles, exclude appearances, and deduplicate repeated
album and track IDs; alternate releases with different track IDs may remain.
Artist downloads can be large; **Match tracks** previews them first. Choose a preferred music source, maximum quality, and
original/FLAC/MP3/Opus output.

**Match tracks** performs matching without downloading audio. **Download music**
resolves and downloads the tracks. Matching prefers ISRCs when present, otherwise
requires similar titles/artists and compatible durations, rejecting live/remix/
cover substitutions and ambiguous results. It may conservatively skip valid
recordings; matching is not guaranteed to identify every song.

Optional fallback tries the preferred source first, then configured sources in
Qobuz → Deezer → Tidal → YouTube Music order, excluding the preferred one.
Without fallback, only the selected source is used. Both missing matches and
source/download errors can trigger fallback. Unavailable/local Spotify items and
episodes are excluded; paginated track entries are retained in order.

Downloads default to `~/Downloads/Yoinker/Music/<playlist or song>/` with embedded
source metadata and artwork from streamrip. `matches.json` / `downloads.json`
record matched, unmatched, and failed tracks under
`~/.local/state/yoinker/reports/<destination-hash>/` (or `$XDG_STATE_HOME`).
The popup prints the report location. Temporary `__artwork` directories are
removed after the operation; embedded covers remain inside the audio files. A partial playlist produces a
partial-completion status, not a success message. Completed streamrip tracks are
tracked with hidden marker files so retries skip them; interrupted tracks retry.
YouTube Music uses yt-dlp's normal resume/skip behavior.

[Streamrip](https://github.com/nathom/streamrip) supports Qobuz, Deezer, and Tidal;
its active clients do not include YouTube Music. That source uses
[ytmusicapi](https://github.com/sigma67/ytmusicapi) for song search and yt-dlp for
audio downloads. YouTube audio remains lossy regardless of a FLAC output choice.
The quality cap is clamped to each service's supported range; YouTube Music uses
its best available audio.

## Search by title

Choose **Search titles**, type a song title (add an artist for more precise results),
and click **Search** or press Enter. The lookup uses ytmusicapi’s YouTube Music
song catalog without Spotify login. Up to 20 selectable results show title,
artists, album, and duration. Select a result, choose a download source/format,
then click **Download music** or **Match tracks**. YouTube Music downloads the
exact selected video ID; Qobuz/Deezer/Tidal match its metadata using the existing
confidence checks and optional fallback. Search result metadata normally has no
ISRC, so catalog matches may be less certain than a Spotify track lookup.

## YouTube downloads

Paste a YouTube link, choose Video or Audio, then use the quality, format,
metadata, and subtitle buttons. **Available formats** displays yt-dlp's format
list. Destinations default to `~/Downloads/Yoinker/Video` or `/Audio`.

**Clear** at the top empties the link and progress log, preserving download
options and saved accounts. It is disabled during an operation.

Progress/errors appear in the popup. Closing it leaves the operation running;
reopen to check it or press **Cancel** to stop. Shell/plugin reloads interrupt
operations. The helper disables Python bytecode writes so Omarchy’s plugin watcher does not
reload the shell when a download imports a module. Jobs belong to their bar instance; there is no shared multi-monitor
queue yet. The original terminal wizard remains available as `python3 download.py`.

MP4/MKV remuxing does not re-encode incompatible codecs; use Auto or MKV if a
container fails. English subtitles must exist on the source; automatic captions
are not requested. Existing yt-dlp config is ignored. YouTube links containing a
playlist download only the selected video.

## Development

Inspired by the local ECHO-Downloader / spotify-to-qobuz workflow: Spotify PKCE,
playlist metadata, conservative catalog matching, and per-playlist reports.
Yoinker has its own configuration and does not read or alter ECHO's credentials.
Books, games, and further media providers remain future additions.

```sh
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell BarWidget.qml Configuration.qml
/usr/bin/python -m unittest discover -s tests -v
bash -n install.sh
```

Tests cover source boundaries, argument safety, private credential storage,
Spotify pagination, matching, preview-only behavior, fallback, partial reports,
streamrip configuration, and cold-start helpers leaving the watched plugin directory unchanged. Account-authenticated downloads require your
credentials and have not been verified by these offline tests.
