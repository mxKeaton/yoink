import unittest
import json
import socket
from pathlib import Path
from unittest.mock import patch

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
        self.assertIn('text: "Loading download options"', bar_widget)
        self.assertIn('text: "Downloads will continue in the background"', bar_widget)
        self.assertIn('text: "Movies"', bar_widget)
        self.assertIn('action in (\'movie-trending\', \'movie-search\', \'movie-detail\', \'movie-sources\')', (project / 'backend.py').read_text())
        self.assertNotIn('Game details loaded.', bar_widget)

        loading_button = bar_widget.index('text: "Loading download options"')
        steam_button = bar_widget.index('text: "Steam"')
        self.assertLess(loading_button, steam_button)
        self.assertLess(steam_button, bar_widget.index('text: "GoG"'))

    def test_missing_game_description_stays_empty_until_ui_detail_fallback(self):
        item = {'id': 42, 'name': 'Example'}
        self.assertEqual(games._game(item)['summary'], '')

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

    def test_source_timeout_keeps_a_browser_button(self):
        base = 'https://steamrip.com'
        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': [base]}), \
             patch.object(games, 'urlopen', side_effect=socket.timeout()):
            result = games.source_matches('How to Fish')
        self.assertEqual(result, [{'base': base, 'url': base + '/how-to-fish-free-download/', 'valid': False, 'timeout': True}])

    def test_source_404_stays_hidden(self):
        base = 'https://astralgames.net'
        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': [base]}), \
             patch.object(games, 'urlopen', return_value=_Response('Page not found', base + '/game/how-to-fish', 404)):
            result = games.source_matches('How to Fish')
        self.assertEqual(result, [])

    def test_source_links_exclude_unverified_sites(self):
        configured = [
            'https://steamrip.com',
            'https://ankergames.net',
            'https://astralgames.net',
        ]
        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': configured}), \
             patch.object(games, 'source_matches', return_value=[]):
            result = games.source_links('How To Fish')

        self.assertEqual(result, [])

    def test_source_links_keep_validated_pages(self):
        matched = [{'base': 'https://steamrip.com', 'url': 'https://steamrip.com/how-to-fish-free-download/', 'valid': True}]
        with patch.object(games, 'source_matches', return_value=matched):
            self.assertEqual(games.source_links('How To Fish'), matched)

    def test_store_links_keep_matching_product_pages(self):
        games._STORE_LOOKUP_CACHE.clear()

        def open_url(request, timeout=0):
            return _Response('<a href="/en/game/how-to-fish">How To Fish</a>', request.full_url)

        with patch.object(games, 'urlopen', side_effect=open_url):
            result = games.store_links('How To Fish')

        self.assertEqual({item['id'] for item in result}, {'gog'})
        self.assertEqual({item['url'] for item in result}, {'https://www.gog.com/en/game/how-to-fish'})

    def test_store_links_use_catalog_apis(self):
        games._STORE_LOOKUP_CACHE.clear()

        def open_url(request, timeout=0):
            if 'catalog.gog.com' in request.full_url:
                return _Response(json.dumps({'products': [
                    {'title': 'Stardew Valley', 'slug': 'stardew_valley'}
                ]}), request.full_url)
            raise AssertionError('The HTML fallback should not run after a valid GoG API response.')

        with patch.object(games, 'urlopen', side_effect=open_url):
            result = games.store_links('Stardew Valley')

        self.assertEqual({item['id'] for item in result}, {'gog'})
        self.assertEqual({item['url'] for item in result}, {'https://www.gog.com/en/game/stardew_valley'})

    def test_store_links_hide_searches_without_matching_product(self):
        games._STORE_LOOKUP_CACHE.clear()
        with patch.object(games, 'urlopen', return_value=_Response('<p>No results found</p>', 'https://example.test')):
            self.assertEqual(games.store_links('How To Fish'), [])

    def test_known_sources_use_canonical_routes(self):
        requests = []

        def open_url(request, timeout=0):
            requests.append(request.full_url)
            return _Response('valid game page', request.full_url)

        with patch.object(games.settings, 'load', return_value={'game_always_checked_urls': [
            'https://steamrip.com', 'https://ankergames.net', 'https://astralgames.net']
        }), patch.object(games, 'urlopen', side_effect=open_url):
            result = games.source_matches('How To Fish')
        expected = [
            'https://steamrip.com/how-to-fish-free-download/',
            'https://ankergames.net/game/how-to-fish',
            'https://astralgames.net/game/how-to-fish',
        ]
        self.assertEqual(set(requests), set(expected))
        self.assertEqual(set(item['url'] for item in result), set(expected))


if __name__ == '__main__':
    unittest.main()
