import unittest
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


if __name__ == '__main__':
    unittest.main()
