import unittest
from unittest.mock import patch

import games


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


if __name__ == '__main__':
    unittest.main()
