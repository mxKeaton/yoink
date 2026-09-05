import contextlib
import io
import unittest
from unittest.mock import patch

import lookup
import spotify


class SpotifyCollectionTests(unittest.TestCase):
    def test_album_and_artist_link_types(self):
        for kind in ('album', 'artist'):
            identity = 'A' * 22
            for link in (f'https://open.spotify.com/{kind}/{identity}?si=x', f'spotify:{kind}:{identity}'):
                self.assertEqual(spotify.spotify_source(link), (kind, identity))

    def test_album_tracks_follow_pagination(self):
        first = {'name': 'Album', 'tracks': {'items': [{'id': 'one', 'name': 'One'}], 'next': 'https://api.spotify.com/v1/albums/test/tracks?offset=1'}}
        second = {'items': [{'id': 'two', 'name': 'Two'}], 'next': None}
        with patch.object(spotify, 'request_json', side_effect=[first, second]) as request:
            name, tracks = spotify.spotify_album('test', 'token')
            self.assertEqual(name, 'Album')
            self.assertEqual([t['id'] for t in tracks], ['one', 'two'])
            self.assertEqual(request.call_count, 2)

    def test_artist_collects_albums_singles_and_deduplicates(self):
        with patch.object(spotify, 'request_json', return_value={'name': 'Artist'}), patch.object(spotify, 'paginated_items', return_value=[{'id': 'album1'}, {'id': 'album1'}, {'id': 'album2'}]), patch.object(spotify, 'spotify_album', side_effect=[('One', [{'id': 'a'}]), ('Two', [{'id': 'a'}, {'id': 'b'}])]) as albums, contextlib.redirect_stdout(io.StringIO()):
            name, tracks = spotify.spotify_artist('artist', 'token')
            self.assertEqual(name, 'Artist')
            self.assertEqual([t['id'] for t in tracks], ['a', 'b'])
            self.assertEqual(albums.call_count, 2)

    def test_bad_pagination_rejected(self):
        with self.assertRaises(RuntimeError):
            list(spotify.paginated_items('https://other.test/', 'token'))


class LookupTests(unittest.TestCase):
    def test_search_filters_normalizes_and_deduplicates(self):
        song = {'resultType': 'song', 'videoId': 'abcdefghijk', 'title': 'Song', 'artists': [{'name': 'Artist'}], 'duration_seconds': 180, 'duration': '3:00', 'album': {'name': 'Album'}}
        with patch('ytmusicapi.YTMusic') as api:
            api.return_value.search.return_value = [song, song, {'resultType': 'video', 'videoId': '12345678901'}]
            results = lookup.search('Artist Song')
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['album'], 'Album')
            track = lookup.selected_track(results[0])
            self.assertEqual(track['duration_ms'], 180000)
            self.assertEqual(track['youtube_id'], 'abcdefghijk')

    def test_bad_selected_result_rejected(self):
        for value in ({}, {'videoId': '../path'}, {'videoId': 'abcdefghijk', 'title': 'Song', 'artists': []}):
            with self.assertRaises(ValueError):
                lookup.selected_track(value)
