import tempfile
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

import book_download


class _Response:
    def __init__(self, body, content_type='application/octet-stream'):
        self._body = body if isinstance(body, bytes) else body.encode()
        self.headers = Message()
        self.headers['Content-Length'] = str(len(self._body))
        self.headers['Content-Type'] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if size < 0:
            value, self._body = self._body, b''
            return value
        value, self._body = self._body[:size], self._body[size:]
        return value


class _Client:
    def __init__(self):
        self.pages = {
            'http://stash.test/index.php?req=Clean%20Code&open=0&res=25&view=simple&phrase=1&column=def':
                '<a href="/books/clean-code">Clean Code</a>',
            'http://stash.test/books/clean-code': '<a href="/files/clean-code.epub">Download EPUB</a>',
        }

    def html(self, url, **_kwargs):
        return self.pages[url]

    def open(self, url, **_kwargs):
        self.last_url = url
        return _Response(b'book contents')


class _LibgenShapeClient:
    """Small fixture matching the reference script's opaque-link flow."""

    def __init__(self):
        self.pages = {
            'http://stash.test/index.php?req=Clean%20Code&open=0&res=25&view=simple&phrase=1&column=def':
                '<a href="/ads.php?md5=ABC123">record</a>',
            'http://stash.test/ads.php?md5=ABC123':
                '<a href="get.php?md5=ABC123&key=SECRET">GET</a>',
        }

    def html(self, url, **_kwargs):
        return self.pages[url]

    def open(self, url, **_kwargs):
        self.last_url = url
        return _Response(b'book contents')


class _LibgenEditionClient:
    """Fixture where an edition page offers both TOR and ads.php links."""

    def __init__(self):
        self.pages = {
            'http://stash.test/index.php?req=Clean%20Code&open=0&res=25&view=simple&phrase=1&column=def':
                '<a href="/edition.php?id=123">Clean Code</a>',
            'http://stash.test/edition.php?id=123': (
                '<a href="http://mirror.test/Clean%20Code.epub">TOR mirror</a>'
                '<a href="/ads.php?md5=ABC123">Libgen</a>'
            ),
            'http://stash.test/ads.php?md5=ABC123':
                '<a href="get.php?md5=ABC123&key=SECRET">GET</a>',
        }

    def html(self, url, **_kwargs):
        return self.pages[url]

    def open(self, url, **_kwargs):
        self.last_url = url
        return _Response(b'book contents')


class BookDownloadTests(unittest.TestCase):
    def test_source_errors_are_actionable(self):
        error = HTTPError('http://stash.test/search', 404, 'not found', {}, None)
        self.assertIn('HTTP 404', book_download.describe_error(error, error.url))
        self.assertIn('source address', book_download.describe_error(error, error.url))

    def test_matching_and_streaming_use_configured_source(self):
        config = {
            'book_download_source': {
                'base_url': 'http://stash.test',
            }
        }
        selected = {'id': '123', 'name': 'Clean Code', 'author': 'Robert Martin', 'extension': 'epub'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(book_download.settings, 'load', return_value=config), \
             patch.object(book_download, '_SourceClient', _Client):
            result = book_download.download(selected, {'output': directory})
            saved = Path(result['path'])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_bytes(), b'book contents')
            self.assertEqual(saved.suffix, '.epub')

    def test_download_source_defaults_without_settings(self):
        with patch.object(book_download.settings, 'load', return_value={}):
            self.assertEqual(book_download._source_config(), {'base_url': 'https://libgen.li'})

    def test_book_download_uses_settings_directory(self):
        config = {
            'book_download_source': {'base_url': 'http://stash.test'},
        }
        selected = {'id': '123', 'name': 'Clean Code', 'author': 'Robert Martin', 'extension': 'epub'}
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / 'configured-books')
            config['book_download_path'] = output
            with patch.object(book_download.settings, 'load', return_value=config), \
                 patch.object(book_download, '_SourceClient', _Client):
                result = book_download.download(selected, {'output': ''})
            self.assertEqual(Path(result['path']).parent, Path(output))

    def test_reference_index_ads_get_shape(self):
        config = {
            'book_download_source': {
                'base_url': 'http://stash.test',
            }
        }
        selected = {'id': '123', 'name': 'Clean Code', 'extension': 'epub'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(book_download.settings, 'load', return_value=config), \
             patch.object(book_download, '_SourceClient', _LibgenShapeClient):
            result = book_download.download(selected, {'output': directory})
            self.assertEqual(Path(result['path']).read_bytes(), b'book contents')
            self.assertEqual(result['url'], 'http://stash.test/get.php?md5=ABC123&key=SECRET')

    def test_unrelated_non_http_anchors_do_not_break_search(self):
        config = {'base_url': 'http://stash.test'}
        markup = (
            '<a href="ftp://files.test/upload">upload</a>'
            '<a href="bitcoin://wallet">donate</a>'
            '<a href="/ads.php?md5=ABC123">record</a>'
        )
        matches = book_download._find_matches(markup, {'name': 'Unknown'}, config)
        self.assertEqual([item['url'] for item in matches], ['http://stash.test/ads.php?md5=ABC123'])

    def test_session_entry_is_preferred_over_direct_mirror(self):
        config = {'book_download_source': {'base_url': 'http://stash.test'}}
        selected = {'name': 'Clean Code', 'extension': 'epub'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(book_download.settings, 'load', return_value=config), \
             patch.object(book_download, '_SourceClient', _LibgenEditionClient):
            result = book_download.download(selected, {'output': directory})
            self.assertEqual(result['url'], 'http://stash.test/get.php?md5=ABC123&key=SECRET')

    def test_selected_source_edition_url_skips_title_search(self):
        config = {'book_download_source': {'base_url': 'http://stash.test'}}
        selected = {
            'name': 'Clean Code',
            'extension': 'epub',
            'url': 'http://stash.test/edition.php?id=123',
        }
        client = _LibgenEditionClient()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(book_download.settings, 'load', return_value=config), \
             patch.object(book_download, '_SourceClient', lambda: client):
            result = book_download.download(selected, {'output': directory})
            self.assertEqual(result['url'], 'http://stash.test/get.php?md5=ABC123&key=SECRET')


if __name__ == '__main__':
    unittest.main()
