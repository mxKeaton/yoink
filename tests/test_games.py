import unittest
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import games


class _Response:
    def __init__(self, body, url, status=200):
        self._body = body.encode()
        self._url = url
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size=-1):
        return self._body

    def geturl(self):
        return self._url


class GameCatalogueTests(unittest.TestCase):
    def test_plugin_version_is_visible_and_matches_manifest(self):
        project = Path(__file__).resolve().parents[1]
        manifest = json.loads((project / 'manifest.json').read_text())
        bar_widget = (project / 'BarWidget.qml').read_text()
        configuration = (project / 'Configuration.qml').read_text()
        self.assertIn('pluginVersion: "' + manifest['version'] + '"', bar_widget)
        self.assertIn('property string pluginVersion', configuration)
        self.assertIn('Yoink version " + root.pluginVersion', configuration)

    def test_trending_uses_no_key_steam_feed(self):
        item = {'id': 42, 'name': 'Example', 'summary': 'A game'}
        with patch.object(games.settings, 'load', return_value={'igdb_client_id': 'id', 'igdb_client_secret': 'secret'}), \
             patch.object(games, '_steam_trending', return_value=[games._game(item)]):
            result = games.trending()
        self.assertEqual(result[0]['id'], '42')
        self.assertIn('library_600x900_2x.jpg', result[0]['cover'])
        self.assertNotIn('steamdbUrl', result[0])

    def test_search_falls_back_to_steam(self):
        with patch.object(games.settings, 'load', return_value={}), \
             patch.object(games, '_json', return_value={'items': [{'appid': 7, 'name': 'Fallback'}]}):
            result = games.search('Fallback')
        self.assertEqual(result[0]['source'], 'steam')
        self.assertEqual(result[0]['id'], '7')

    def test_invalid_search_is_rejected(self):
        with self.assertRaises(ValueError):
            games.search('')

    def test_ankergames_reader_recovers_cloudflare_page(self):
        games._ANKER_LOOKUP_CACHE.clear()

        def open_url(request, timeout=0):
            if request.full_url.startswith('https://ankergames.net/'):
                raise HTTPError(request.full_url, 403, 'challenge', {}, None)
            return _Response(
                'Title: How to Fish Free Download (v1.0.12) | AnkerGames\n',
                request.full_url,
            )

        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': ['https://ankergames.net']}), \
             patch.object(games, 'urlopen', side_effect=open_url):
            result = games.source_matches('How to Fish')
        self.assertEqual(result[0]['url'], 'https://ankergames.net/game/how-to-fish')

    def test_ankergames_reader_rejects_missing_page(self):
        games._ANKER_LOOKUP_CACHE.clear()

        def open_url(request, timeout=0):
            if request.full_url.startswith('https://ankergames.net/'):
                raise HTTPError(request.full_url, 403, 'challenge', {}, None)
            return _Response(
                'Title: AnkerGames - Free Pre-installed PC Games\n'
                'Warning: Target URL returned error 404: Not Found\n',
                request.full_url,
            )

        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': ['https://ankergames.net']}), \
             patch.object(games, 'urlopen', side_effect=open_url):
            result = games.source_matches('Marvel Rivals')
        self.assertEqual(result, [])

    def test_source_links_include_every_configured_site_when_probing_fails(self):
        configured = [
            'https://steamrip.com',
            'https://ankergames.net',
            'https://astralgames.net',
        ]
        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': configured}), \
             patch.object(games, 'source_matches', return_value=[]):
            result = games.source_links('How To Fish')

        self.assertEqual([item['base'] for item in result], configured)
        self.assertEqual([item['url'] for item in result], [
            'https://steamrip.com/how-to-fish',
            'https://ankergames.net/game/how-to-fish',
            'https://astralgames.net/how-to-fish',
        ])
        self.assertTrue(all(item['valid'] is False for item in result))


if __name__ == '__main__':
    unittest.main()
