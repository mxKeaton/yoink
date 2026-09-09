import unittest
from unittest.mock import patch

import movies


class MovieCatalogueTests(unittest.TestCase):
    def test_rive_numeric_secret_matches_browser_algorithm(self):
        self.assertEqual(movies._secret("1204680"), "NTY1NDI1ODU=")

    def test_trending_normalizes_tmdb_results(self):
        payload = {"results": [{
            "id": 1204680,
            "title": "Coyote vs. Acme",
            "overview": "A comedy.",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "release_date": "2023-01-01",
            "vote_average": 8.1,
        }]}
        with patch.object(movies, "_backend", return_value=payload) as backend:
            result = movies.trending(2)
        backend.assert_called_once_with("trendingMovie", page=2)
        self.assertEqual(result[0]["id"], "1204680")
        self.assertEqual(result[0]["name"], "Coyote vs. Acme")
        self.assertEqual(result[0]["year"], "2023")
        self.assertEqual(result[0]["mediaType"], "movie")
        self.assertIn("image.tmdb.org/t/p/w342/poster.jpg", result[0]["gridCover"])

    def test_trending_tv_uses_tv_request_and_first_air_date(self):
        payload = {"results": [{
            "id": 1399,
            "name": "Game of Thrones",
            "overview": "A fantasy drama.",
            "poster_path": "/poster.jpg",
            "first_air_date": "2011-04-17",
            "vote_average": 9.2,
        }]}
        with patch.object(movies, "_backend", return_value=payload) as backend:
            result = movies.trending(3, "tv")
        backend.assert_called_once_with("trendingTv", page=3)
        self.assertEqual(result[0]["name"], "Game of Thrones")
        self.assertEqual(result[0]["year"], "2011")
        self.assertEqual(result[0]["mediaType"], "tv")

    def test_search_uses_combined_movie_and_tv_request(self):
        payload = {"results": [
            {"id": 1, "media_type": "movie", "title": "Movie"},
            {"id": 2, "media_type": "tv", "name": "Show"},
            {"id": 3, "media_type": "person", "name": "Actor"},
        ]}
        with patch.object(movies, "_backend", return_value=payload) as backend:
            result = movies.search("title", 2)
        backend.assert_called_once_with("searchMulti", page=2, query="title")
        self.assertEqual([item["name"] for item in result], ["Movie", "Show"])
        self.assertEqual([item["mediaType"] for item in result], ["movie", "tv"])

    def test_search_rejects_blank_queries(self):
        with self.assertRaises(ValueError):
            movies.search(" ")

    def test_detail_adds_movie_metadata(self):
        payload = {
            "id": 42,
            "title": "Example",
            "overview": "Description",
            "genres": [{"name": "Drama"}],
            "runtime": 96,
            "tagline": "A line.",
        }
        with patch.object(movies, "_backend", return_value=payload):
            result = movies.detail("42")
        self.assertEqual(result["genres"], ["Drama"])
        self.assertEqual(result["runtime"], 96)
        self.assertEqual(result["tagline"], "A line.")

    def test_detail_adds_tv_metadata(self):
        payload = {
            "id": 1399,
            "name": "Game of Thrones",
            "overview": "Description",
            "first_air_date": "2011-04-17",
            "genres": [{"name": "Drama"}],
            "episode_run_time": [57],
            "number_of_seasons": 8,
            "number_of_episodes": 73,
        }
        with patch.object(movies, "_backend", return_value=payload) as backend:
            result = movies.detail("1399", "tv")
        backend.assert_called_once_with("tvData", movie_id="1399")
        self.assertEqual(result["mediaType"], "tv")
        self.assertEqual(result["runtime"], 57)
        self.assertEqual(result["seasons"], 8)
        self.assertEqual(result["episodes"], 73)

    def test_source_links_adds_validated_movie_sites(self):
        responses = {
            "apex": [{"provider": "apex", "url": "https://one.test/a"}],
            "pulse": [{"provider": "pulse", "url": "https://one.test/a"}],
            "guru": [{"provider": "guru", "url": "https://two.test/b"}],
        }
        with patch.object(movies, "_provider_names", return_value=["apex", "pulse", "guru"]), \
             patch.object(movies, "_provider_sources", side_effect=lambda provider, movie_id: responses[provider]), \
             patch.object(movies, "_page_available", return_value=True):
            result = movies.source_links("42")
        self.assertEqual([item["label"] for item in result], ["Rive", "7Movies", "Movy", "bCine"])
        self.assertEqual([item["watchUrl"] for item in result], [
            "https://www.rivestream.app/watch?type=movie&id=42",
            "https://7movies.in/?open=movie-42&watch=1",
            "https://www.movy.sx/movie/42/watch",
            "https://bcine.ru/movie/42",
        ])

    def test_source_links_hides_unavailable_movie_sites(self):
        with patch.object(movies, "_provider_names", return_value=[]), \
             patch.object(movies, "_page_available", side_effect=lambda url: "7movies.in" in url):
            result = movies.source_links("42")
        self.assertEqual([item["label"] for item in result], ["7Movies"])

    def test_source_links_builds_tv_routes(self):
        with patch.object(movies, "_provider_names", return_value=[]), \
             patch.object(movies, "_page_available", return_value=True):
            result = movies.source_links("1399", "tv")
        self.assertEqual([item["watchUrl"] for item in result], [
            "https://www.rivestream.app/watch?type=tv&id=1399",
            "https://7movies.in/?open=tv-1399&watch=1",
            "https://www.movy.sx/tv/1399/watch",
            "https://bcine.ru/tv/1399",
        ])


if __name__ == "__main__":
    unittest.main()
