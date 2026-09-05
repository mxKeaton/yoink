"""Spotify metadata -> conservative catalog matching -> streamrip/yt-dlp."""
import asyncio
import hashlib
import os
import json
import logging
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

import settings
import spotify

SOURCES = ('qobuz', 'deezer', 'tidal', 'youtube')


def normalize(text):
    return ' '.join(re.findall(r'\w+', str(text).casefold()))


def candidate(item, source):
    artists = item.get('artists') or [item.get('performer') or item.get('artist') or {}]
    if not isinstance(artists, list):
        artists = [artists]
    names = [a.get('name', '') if isinstance(a, dict) else str(a) for a in artists]
    return {
        'id': str(item.get('videoId') or item.get('id', '')),
        'title': item.get('title') or item.get('name', ''),
        'artists': names,
        'duration': item.get('duration_seconds') or item.get('duration') or 0,
        'isrc': item.get('isrc', ''), 'source': source,
    }


def match_score(track, item):
    isrc = track.get('external_ids', {}).get('isrc')
    if isrc and item.get('isrc'):
        return 1.0 if isrc.upper() == item['isrc'].upper() else 0.0
    title = normalize(track['name'])
    other = normalize(item['title'])
    # Avoid substituting covers, live versions, remixes, or instrumental tracks.
    versions = {'live', 'remix', 'instrumental', 'karaoke', 'cover', 'acoustic', 'sped', 'slowed'}
    if set(title.split()) & versions != set(other.split()) & versions:
        return 0.0
    title_score = SequenceMatcher(None, title, other).ratio()
    artist_score = max((SequenceMatcher(None, normalize(a['name']), normalize(b)).ratio()
                        for a in track.get('artists', []) for b in item['artists']), default=0)
    if title_score < .83 or artist_score < .85:
        return 0.0
    duration = float(item.get('duration') or 0)
    wanted = float(track.get('duration_ms') or 0) / 1000
    if wanted and duration and abs(wanted - duration) > max(5, wanted * .025):
        return 0.0
    return min(.99, .65 * title_score + .35 * artist_score)


def best_match(track, items):
    ranked = sorted(((match_score(track, item), item) for item in items if re.fullmatch(r'[A-Za-z0-9_-]+', item['id'])), key=lambda p: p[0], reverse=True)
    if not ranked or ranked[0][0] < .9:
        return None
    # Tied metadata for different recordings is ambiguous unless ISRC is exact.
    if len(ranked) > 1 and ranked[0][0] < 1 and ranked[0][0] - ranked[1][0] < .02:
        return None
    return ranked[0][1]


def configured(source, data):
    return {'qobuz': bool(data.get('qobuz_user_id') and data.get('qobuz_token')) if settings.qobuz_auth_mode(data) == 'token' else bool(data.get('qobuz_email') and data.get('qobuz_password')),
            'deezer': bool(data.get('deezer_arl')),
            'tidal': bool(data.get('tidal_access_token') and data.get('tidal_user_id') and data.get('tidal_country_code') and data.get('tidal_token_expiry')),
            'youtube': True}[source]


def make_config(data, output, quality, codec):
    from streamrip.config import Config
    config = Config.defaults()
    c = config.session
    c.downloads.folder = str(output)
    c.downloads.concurrency = False
    c.database.downloads_enabled = False
    c.database.failed_downloads_enabled = False
    c.cli.progress_bars = False
    c.cli.text_output = False
    c.misc.check_for_updates = False
    c.filepaths.add_singles_to_folder = False
    c.filepaths.track_format = '{artist} - {title} [{id}]'
    c.conversion.enabled = codec != 'original'
    c.conversion.codec = codec.upper()
    c.conversion.lossy_bitrate = 320
    c.conversion.sampling_rate = 192000
    c.conversion.bit_depth = 24
    c.qobuz.quality = max(1, min(4, quality))
    c.deezer.quality = min(2, quality)
    c.deezer.use_deezloader = False
    c.tidal.quality = min(3, quality)
    c.qobuz.use_auth_token = settings.qobuz_auth_mode(data) == 'token'
    c.qobuz.app_id = data.get('qobuz_app_id', '')
    c.qobuz.secrets = [data['qobuz_app_secret']] if data.get('qobuz_app_secret') else []
    c.qobuz.email_or_userid = data.get('qobuz_user_id' if c.qobuz.use_auth_token else 'qobuz_email', '')
    c.qobuz.password_or_token = data.get('qobuz_token' if c.qobuz.use_auth_token else 'qobuz_password', '')
    c.deezer.arl = data.get('deezer_arl', '')
    for key in ('user_id', 'country_code', 'access_token', 'refresh_token', 'token_expiry'):
        setattr(c.tidal, key, data.get('tidal_' + key, ''))
    return config


class Catalogs:
    def __init__(self, config, data):
        self.config, self.data = config, data
        self.clients = {}
        self.unavailable = set()

    async def client(self, source):
        if source not in self.clients:
            from streamrip.client import QobuzClient, DeezerClient, TidalClient
            client = {'qobuz': QobuzClient, 'deezer': DeezerClient, 'tidal': TidalClient}[source](self.config)
            self.clients[source] = client
            await asyncio.wait_for(client.login(), 90)
            if source == 'tidal':
                c = self.config.session.tidal
                settings.update({'tidal_' + key: str(getattr(c, key)) for key in
                                 ('user_id', 'country_code', 'access_token', 'refresh_token', 'token_expiry')})
        return self.clients[source]

    async def search(self, source, track):
        query = ' '.join(a['name'] for a in track['artists']) + ' ' + track['name']
        if source == 'youtube':
            from ytmusicapi import YTMusic
            items = await asyncio.to_thread(YTMusic().search, query, filter='songs', limit=12)
            return [candidate(i, source) for i in items if i.get('resultType') == 'song']
        client = await self.client(source)
        pages = await asyncio.wait_for(client.search('track', query, limit=15), 60)
        items = []
        for page in pages:
            items += page.get('tracks', {}).get('items', []) if source == 'qobuz' else page.get('data' if source == 'deezer' else 'items', [])
        results = [candidate(i, source) for i in items]
        # Fetch recording IDs/durations for the closest results when search omits them.
        closest = sorted(results, key=lambda i: SequenceMatcher(None, normalize(track['name']), normalize(i['title'])).ratio(), reverse=True)[:4]
        for item in closest:
            if not item['isrc']:
                metadata = await asyncio.wait_for(client.get_metadata(item['id'], 'track'), 45)
                item.update(candidate(metadata, source))
        return results

    async def download(self, match, output, codec):
        source = match['source']
        if source == 'youtube':
            args = ['yt-dlp', '--ignore-config', '--no-playlist', '--no-overwrites', '--newline', '--no-colors',
                    '-f', 'bestaudio/best', '-x', '--audio-format', 'best' if codec == 'original' else codec,
                    '--audio-quality', '0', '--embed-metadata', '--paths', str(output),
                    '-o', '%(artist,uploader)s - %(title).150B [%(id)s].%(ext)s']
            cookies = self.data.get('youtube_cookies', '')
            if cookies:
                args += ['--cookies', str(Path(cookies).expanduser())]
            args += ['--', 'https://music.youtube.com/watch?v=' + match['id']]
            process = await asyncio.create_subprocess_exec(*args)
            try:
                code = await process.wait()
            except asyncio.CancelledError:
                process.terminate()
                await process.wait()
                raise
            if code:
                raise RuntimeError('YouTube Music download failed.')
            return
        from streamrip.media import PendingSingle
        from streamrip.db import Database, Dummy
        client = await self.client(source)
        media = await PendingSingle(match['id'], client, self.config, Database(Dummy(), Dummy())).resolve()
        if media is None:
            raise RuntimeError('The matched recording is not streamable with this account.')
        await media.preprocess()
        # Do not overwrite a completed track during playlist retries.
        marker = output / f'.yoinker-{source}-{match["id"]}-{codec}.json'
        if marker.exists():
            completed = Path(json.loads(marker.read_text())['path'])
            if completed.is_file() and completed.stat().st_size:
                print('Already completed; skipped.', flush=True)
                return
        # Direct streamrip download propagates errors instead of its CLI's
        # catch-and-continue behavior, so partial files never count as success.
        received = 0
        last_update = 0
        def progress(amount):
            nonlocal received, last_update
            received += amount
            if received - last_update >= 2 * 1024 * 1024:
                print(f'  Downloaded {received / 1024 / 1024:.1f} MiB', flush=True)
                last_update = received
        await media.downloadable.download(media.download_path, progress)
        await media.postprocess()
        if not Path(media.download_path).is_file() or not Path(media.download_path).stat().st_size:
            raise RuntimeError('No completed output file was produced.')
        marker.write_text(json.dumps({'path': media.download_path}))

    async def close(self):
        for client in self.clients.values():
            session = getattr(client, 'session', None)
            if session and not session.closed:
                await session.close()


def report_directory(output):
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state')))
    identity = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:20]
    folder = state / 'yoinker' / 'reports' / identity
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def safe_folder(value):
    return re.sub(r'[^\w .-]', '_', value).strip(' .')[:100] or 'Spotify'


async def run(options):
    source = options.get('source', 'qobuz')
    codec = options.get('musicCodec', 'original')
    quality = int(options.get('musicQuality', 3))
    if source not in SOURCES or codec not in ('original', 'mp3', 'flac', 'opus') or quality not in range(1, 5):
        raise ValueError('Invalid music download options.')
    import shutil
    if not shutil.which('ffmpeg'):
        raise ValueError('Install ffmpeg before downloading music.')
    if options.get('selection'):
        from lookup import selected_track
        track = selected_track(options['selection'])
        name, tracks = track['name'], [track]
    else:
        print('Reading Spotify metadata…', flush=True)
        name, tracks = spotify.tracks_from_link(options['url'].strip())
    data = settings.load()
    order = [source] + ([s for s in SOURCES if s != source and configured(s, data)] if options.get('fallback') else [])
    if not any(configured(s, data) for s in order):
        raise ValueError('Configure the selected source or enable fallback in Yoinker first.')
    output = Path(options.get('output', '').strip() or str(Path.home() / 'Downloads' / 'Yoinker' / 'Music')).expanduser().absolute() / safe_folder(name)
    output.mkdir(parents=True, exist_ok=True)
    config = make_config(data, output, quality, codec)
    catalogs = Catalogs(config, data)
    report = []
    reports = report_directory(output)
    preview = options.get('action') == 'match'
    try:
        for number, track in enumerate(tracks, 1):
            label = ', '.join(a['name'] for a in track.get('artists', [])) + ' — ' + track['name']
            print(f'[{number}/{len(tracks)}] {label}', flush=True)
            row = {'spotify_id': track.get('id'), 'title': label, 'status': 'unmatched'}
            for provider in order:
                if not configured(provider, data) or provider in catalogs.unavailable:
                    continue
                try:
                    if provider == 'youtube' and track.get('youtube_id'):
                        match = {'id': track['youtube_id'], 'source': 'youtube', 'title': track['name'],
                                 'artists': [a['name'] for a in track['artists']], 'duration': track['duration_ms'] / 1000}
                    else:
                        matches = await catalogs.search(provider, track)
                        match = best_match(track, matches)
                    if not match:
                        print(f'  {provider}: no confident match.', flush=True)
                        continue
                    print(f'  Matched {provider}: {match["title"]}', flush=True)
                    if not preview:
                        await catalogs.download(match, output, codec)
                    row.update(status='matched' if preview else 'downloaded', match=match)
                    break
                except (ImportError, ModuleNotFoundError):
                    print(f'  {provider}: missing dependency; install streamrip and python-ytmusicapi.', flush=True)
                    catalogs.unavailable.add(provider)
                except Exception as error:
                    # Library exceptions can contain signed URLs/tokens. Never send them to the popup.
                    print(f'  {provider}: {type(error).__name__}; check credentials, account access, or connection.', flush=True)
                    if provider in catalogs.clients and not catalogs.clients[provider].logged_in:
                        catalogs.unavailable.add(provider)
                    row['status'] = 'failed'
            report.append(row)
            (reports / ('matches.json' if preview else 'downloads.json')).write_text(json.dumps(report, indent=2))
    finally:
        try:
            await catalogs.close()
        finally:
            # Covers have been embedded by postprocess; this is streamrip's
            # own cleanup for artwork directories created by this process.
            from streamrip.media import remove_artwork_tempdirs
            remove_artwork_tempdirs()
    count = sum(r['status'] in ('matched', 'downloaded') for r in report)
    print(f'{count}/{len(tracks)} tracks {"matched" if preview else "completed"}. Report: {reports}', flush=True)
    return 0 if count == len(tracks) else 2
