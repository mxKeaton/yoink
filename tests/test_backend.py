"""Exercise the real cold-start helper, including imports and its stdin bridge."""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import backend


class BackendStartupTests(unittest.TestCase):
    def test_game_detail_includes_configured_source_and_store_links(self):
        result = {'id': '42', 'name': 'How To Fish'}
        links = {'sources': [{'base': 'https://steamrip.com', 'url': 'https://steamrip.com/how-to-fish', 'valid': False}],
                 'stores': [{'id': 'gog', 'url': 'https://www.gog.com/en/game/how-to-fish', 'valid': True}]}
        events = []
        output = io.StringIO()
        with patch('games.detail', side_effect=lambda *args: events.append('detail') or result.copy()), \
             patch('games.game_links', side_effect=lambda name: events.append('links') or links), \
             redirect_stdout(output):
            self.assertEqual(backend.main({'action': 'game-detail', 'id': '42'}), 0)
        lines = output.getvalue().splitlines()
        detail_payload = json.loads(lines[0].split('GAME_DETAIL:', 1)[1])
        links_payload = json.loads(lines[1].split('GAME_SOURCES:', 1)[1])
        self.assertEqual(detail_payload, result)
        self.assertEqual(links_payload, links)
        self.assertEqual(events, ['detail', 'links'])

    def test_movie_detail_emits_details_before_sources(self):
        result = {'id': '1204680', 'name': 'Coyote vs. Acme', 'summary': 'Description'}
        sources = [{'label': 'Source 1', 'url': 'https://media.example/movie.m3u8'}]
        events = []
        output = io.StringIO()
        with patch('movies.detail', side_effect=lambda *args: events.append('detail') or result), \
             patch('movies.source_links', side_effect=lambda movie_id: events.append('sources') or sources), \
             redirect_stdout(output):
            self.assertEqual(backend.main({'action': 'movie-detail', 'id': '1204680'}), 0)
        lines = output.getvalue().splitlines()
        self.assertEqual(json.loads(lines[0].split('MOVIE_DETAIL:', 1)[1]), result)
        self.assertEqual(json.loads(lines[1].split('MOVIE_SOURCES:', 1)[1]), sources)
        self.assertEqual(events, ['detail', 'sources'])

    def test_connect_saves_pending_fields_first(self):
        with patch.object(backend.settings, 'save_form') as save, \
             patch.object(backend, 'snapshot'), patch('spotify.connect') as connect:
            self.assertEqual(backend.main({'action': 'spotify-connect',
                                           'values': {'spotify_client_id': 'new-client'}}), 0)
            save.assert_called_once_with({'spotify_client_id': 'new-client'})
            connect.assert_called_once_with()

    def test_runtime_never_writes_into_watched_plugin_directory(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / 'plugin'
            plugin.mkdir()
            for file in ('backend.py', 'download.py', 'music.py', 'settings.py', 'spotify.py', 'lookup.py'):
                shutil.copy2(project / file, plugin / file)
            before = {p.name: p.read_bytes() for p in plugin.iterdir()}
            env = os.environ | {'XDG_CONFIG_HOME': str(root / 'config')}
            # Deliberately no -B flag: the entry point must also protect direct runs.
            operations = [
                {'action': 'config-load'},
                {'action': 'config-save', 'values': {'deezer_arl': 'test-secret'}},
                {'action': 'download', 'url': 'https://invalid.example/video'},
                {'action': 'download', 'url': 'https://open.spotify.com/track/invalid'},
            ]
            for operation in operations:
                result = subprocess.run(['/usr/bin/python', str(plugin/'backend.py')],
                                        input=json.dumps(operation)+'\n', text=True,
                                        capture_output=True, env=env, timeout=20)
                self.assertIn(result.returncode, (0, 1), result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertNotIn('test-secret', result.stdout + result.stderr)
                self.assertEqual({p.name: p.read_bytes() for p in plugin.iterdir()}, before)
            self.assertTrue((root/'config'/'yoink'/'settings.json').exists())


if __name__ == '__main__':
    unittest.main()
