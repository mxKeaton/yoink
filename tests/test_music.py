import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import music
import settings
import spotify

TRACK = {'id': 'a'*22, 'name': 'A Song', 'artists': [{'name': 'An Artist'}], 'duration_ms': 180000, 'external_ids': {'isrc': 'US1234567890'}}


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_secrets_private_and_never_returned(self):
        settings.save_form({'qobuz_password': 'secret', 'deezer_arl': 'cookie'})
        data = settings.load()
        self.assertNotEqual(data['qobuz_password'], 'secret')
        self.assertEqual((settings.directory() / 'settings.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(settings.directory().stat().st_mode & 0o777, 0o700)
        public = settings.public_settings()
        self.assertIs(public['deezer_arl'], True)
        self.assertNotIn('cookie', public.values())
        settings.save_form({'deezer_arl': ''})
        self.assertEqual(settings.load()['deezer_arl'], 'cookie')

    def test_changing_spotify_app_invalidates_login(self):
        settings.update({'spotify_client_id': 'old', 'spotify_token': {'refresh_token': 'secret'}})
        settings.save_form({'spotify_client_id': 'new'})
        self.assertEqual(settings.load()['spotify_token'], {})

    def test_streamrip_config_credentials_and_caps(self):
        config = music.make_config({'qobuz_email': 'user', 'qobuz_password': 'hash', 'deezer_arl': 'cookie'}, Path(self.temp.name), 4, 'flac')
        self.assertEqual(config.session.qobuz.password_or_token, 'hash')
        self.assertEqual(config.session.qobuz.quality, 4)
        self.assertEqual(config.session.deezer.quality, 2)
        self.assertEqual(config.session.tidal.quality, 3)
        self.assertFalse(config.session.deezer.use_deezloader)
        self.assertEqual(config.session.conversion.codec, 'FLAC')

    def test_qobuz_selected_mode_wins_over_saved_other_credentials(self):
        data = {'qobuz_auth_mode': 'password', 'qobuz_email': 'email', 'qobuz_password': 'hash',
                'qobuz_user_id': '123', 'qobuz_token': 'token', 'qobuz_app_id': '456', 'qobuz_app_secret': 'app-secret'}
        config = music.make_config(data, Path(self.temp.name), 3, 'original').session.qobuz
        self.assertFalse(config.use_auth_token)
        self.assertEqual(config.email_or_userid, 'email')
        data['qobuz_auth_mode'] = 'token'
        config = music.make_config(data, Path(self.temp.name), 3, 'original').session.qobuz
        self.assertTrue(config.use_auth_token)
        self.assertEqual(config.email_or_userid, '123')
        self.assertEqual(config.password_or_token, 'token')
        self.assertEqual(config.app_id, '456')
        self.assertEqual(config.secrets, ['app-secret'])
        del data['qobuz_token']
        self.assertFalse(music.configured('qobuz', data))

    def test_qobuz_secret_hidden_preserved_and_mode_migrated(self):
        settings.update({'qobuz_user_id': '123', 'qobuz_token': 'token'})
        self.assertEqual(settings.public_settings()['qobuz_auth_mode'], 'token')
        settings.save_form({'qobuz_app_id': '456', 'qobuz_app_secret': 'app-secret', 'qobuz_auth_mode': 'password'})
        self.assertIs(settings.public_settings()['qobuz_app_secret'], True)
        settings.save_form({'qobuz_app_secret': ''})
        self.assertEqual(settings.load()['qobuz_app_secret'], 'app-secret')
        self.assertEqual(settings.public_settings()['qobuz_auth_mode'], 'password')
        with self.assertRaises(ValueError):
            settings.save_form({'qobuz_auth_mode': 'unknown'})


class MatchingTests(unittest.TestCase):
    def item(self, **changes):
        return {'id': '1', 'title': 'A Song', 'artists': ['An Artist'], 'duration': 180, 'isrc': '', 'source': 'qobuz'} | changes

    def test_first_result_skips_invalid_entries(self):
        self.assertEqual(music.first_result([{'id': 'bad id', 'title': 'Ignored'}, self.item(id='2')]), self.item(id='2'))
        self.assertIsNone(music.first_result([self.item(id='bad id')]))

    def test_preferred_source_first_and_youtube_last(self):
        data = {'qobuz_email': 'x', 'qobuz_password': 'x', 'deezer_arl': 'x'}
        self.assertEqual(music.source_order('deezer', data), ['deezer', 'qobuz', 'youtube'])
        self.assertEqual(music.source_order('tidal', {}), ['youtube'])

    def test_normalize_sources(self):
        for source, item in [('qobuz', {'id': 1, 'performer': {'name': 'An Artist'}}), ('deezer', {'id': 1, 'artist': {'name': 'An Artist'}}), ('tidal', {'id': 1, 'artists': [{'name': 'An Artist'}]}), ('youtube', {'videoId': '1', 'artists': [{'name': 'An Artist'}], 'duration_seconds': 180})]:
            self.assertEqual(music.candidate(item, source)['artists'], ['An Artist'])


class SpotifyTests(unittest.TestCase):
    def test_link_parsing(self):
        self.assertEqual(spotify.spotify_source('https://open.spotify.com/intl-de/track/' + 'a'*22 + '?si=test'), ('track', 'a'*22))
        self.assertEqual(spotify.spotify_source('spotify:playlist:' + 'b'*22), ('playlist', 'b'*22))
        for link in ['https://evil.test/track/'+'a'*22, 'https://open.spotify.com/show/'+'a'*22, 'https://open.spotify.com/track/short']:
            with self.assertRaises(RuntimeError):
                spotify.spotify_source(link)

    def test_playlist_pagination_and_unavailable_items(self):
        pages = [{'items': [{'item': TRACK}, {'item': None}, {'item': {'name': 'Local', 'is_local': True}}], 'next': 'https://api.spotify.com/v1/next'}, {'items': [{'track': TRACK}], 'next': None}]
        with patch.object(spotify, 'request_json', side_effect=pages) as request:
            self.assertEqual(len(spotify.spotify_tracks('a'*22, 'token')), 2)
            self.assertEqual(request.call_count, 2)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        env = patch.dict(os.environ, {'XDG_STATE_HOME': self.state.name})
        env.start()
        self.addCleanup(env.stop)

    def test_selected_search_result_uses_exact_youtube_id(self):
        selection = {'videoId': 'abcdefghijk', 'title': 'Song', 'artists': ['Artist'], 'duration': 180}
        with tempfile.TemporaryDirectory() as tmp, patch.object(spotify, 'tracks_from_link', side_effect=AssertionError('Spotify must not be called')), patch.object(settings, 'load', return_value={}), patch.object(music.Catalogs, 'search', new=AsyncMock(side_effect=AssertionError('Do not search again'))), patch.object(music.Catalogs, 'download', new=AsyncMock()) as download, patch.object(music.Catalogs, 'close', new=AsyncMock()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(asyncio.run(music.run({'selection': selection, 'output': tmp, 'source': 'youtube'})), 0)
            self.assertEqual(download.await_args.args[0]['id'], 'abcdefghijk')

    def test_fallback_and_partial_failure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            match = {'id': '1', 'title': 'A Song', 'artists': ['An Artist'], 'duration': 180, 'isrc': 'US1234567890', 'source': 'youtube'}
            with patch.object(spotify, 'tracks_from_link', return_value=('Playlist', [TRACK])), patch.object(settings, 'load', return_value={'qobuz_email': 'x', 'qobuz_password': 'x'}), patch.object(music.Catalogs, 'search', new=AsyncMock(side_effect=[[], [match]])), patch.object(music.Catalogs, 'download', new=AsyncMock()) as download, patch.object(music.Catalogs, 'close', new=AsyncMock()), contextlib.redirect_stdout(io.StringIO()):
                code = asyncio.run(music.run({'url': 'test', 'output': tmp, 'source': 'qobuz', 'fallback': True}))
                self.assertEqual(code, 0)
                download.assert_awaited_once()
                report = json.loads((music.report_directory(Path(tmp)/'Playlist')/'downloads.json').read_text())
                self.assertEqual(report[0]['match']['source'], 'youtube')
                self.assertFalse((Path(tmp)/'Playlist'/'downloads.json').exists())
            with patch.object(spotify, 'tracks_from_link', return_value=('Missing', [TRACK])), patch.object(settings, 'load', return_value={}), patch.object(music.Catalogs, 'search', new=AsyncMock(return_value=[])), patch.object(music.Catalogs, 'close', new=AsyncMock()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(asyncio.run(music.run({'url': 'test', 'output': tmp, 'source': 'youtube'})), 2)



if __name__ == '__main__':
    unittest.main()

class StreamripDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_callback_and_completed_retry(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            path = output / 'track.flac'
            async def transfer(filename, callback):
                Path(filename).write_bytes(b'audio fixture')
                callback(13)
            media = SimpleNamespace(download_path=str(path), preprocess=AsyncMock(), postprocess=AsyncMock(), downloadable=SimpleNamespace(download=AsyncMock(side_effect=transfer)))
            with patch('streamrip.media.PendingSingle') as pending, contextlib.redirect_stdout(io.StringIO()):
                pending.return_value.resolve = AsyncMock(return_value=media)
                catalogs = music.Catalogs(music.make_config({}, output, 3, 'original'), {})
                catalogs.client = AsyncMock()
                match = {'id': '123', 'source': 'qobuz'}
                await catalogs.download(match, output, 'original')
                await catalogs.download(match, output, 'original')
                media.downloadable.download.assert_awaited_once()
                self.assertTrue((output / '.yoinker-qobuz-123-original.json').exists())

    async def test_failed_transfer_never_marked_complete(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            media = SimpleNamespace(download_path=str(output/'partial.flac'), preprocess=AsyncMock(), postprocess=AsyncMock(), downloadable=SimpleNamespace(download=AsyncMock(side_effect=OSError('interrupted'))))
            with patch('streamrip.media.PendingSingle') as pending:
                pending.return_value.resolve = AsyncMock(return_value=media)
                catalogs = music.Catalogs(music.make_config({}, output, 3, 'original'), {})
                catalogs.client = AsyncMock()
                with self.assertRaises(OSError):
                    await catalogs.download({'id': '123', 'source': 'qobuz'}, output, 'original')
                self.assertFalse(list(output.glob('.yoinker*')))
                media.postprocess.assert_not_awaited()
