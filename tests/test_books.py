import unittest
from unittest.mock import patch

import books


class BookCatalogueTests(unittest.TestCase):
    def test_result_rows_are_normalized_without_extra_dependencies(self):
        markup = '''
        <table id="tablelibgen"><thead><tr><th>Title</th></tr></thead><tbody>
          <tr>
            <td><a title="ID: 116468739" href="edition.php?id=208966739">A Book <i>2</i></a>
              <span>l 8348461</span><font>9780132350884</font></td>
            <td>Jane Doe</td><td>Example Press</td><td>2024</td><td>English</td>
            <td>300</td><td>4 MB</td><td>epub</td>
            <td><a href="/ads.php?md5=0123456789abcdef0123456789abcdef">LibGen</a></td>
          </tr>
        </tbody></table>
        '''
        result = books._parse_results(markup, 'https://libgen.li')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '208966739')
        self.assertEqual(result[0]['name'], 'A Book')
        self.assertEqual(result[0]['author'], 'Jane Doe')
        self.assertEqual(result[0]['extension'], 'epub')
        self.assertIn('images.weserv.nl/?url=libgen.li%2Fcovers%2F8348000', result[0]['cover'])
        self.assertTrue(any('covers.openlibrary.org/isbn/9780132350884' in url for url in result[0]['coverFallbacks']))

    def test_empty_search_is_rejected(self):
        with self.assertRaises(ValueError):
            books.search('')

    def test_cover_fallback_can_use_isbn_without_file_hash(self):
        row = [
            {'text': 'A book', 'anchors': []},
            {'text': 'Jane Doe', 'anchors': []},
            {'text': '9780132350884', 'anchors': []},
        ]
        urls = books._cover_urls(row, '', 'https://libgen.li')
        self.assertEqual(len(urls), 1)
        self.assertIn('covers.openlibrary.org/isbn/9780132350884', urls[0])

    def test_search_page_reports_next_ui_page(self):
        rows = [
            {'id': str(index), 'name': f'Book {index}', 'language': 'English'}
            for index in range(100)
        ]
        def list_page(_query, source_page):
            return (rows, False) if source_page == 1 else ([], False)

        with patch.object(books, '_list_page', side_effect=list_page):
            first = books.search_page('books', 1, 'All')
            sixth = books.search_page('books', 6, 'All')
        self.assertEqual(len(first['items']), 18)
        self.assertTrue(first['has_next'])
        self.assertEqual(len(sixth['items']), 10)
        self.assertFalse(sixth['has_next'])


if __name__ == '__main__':
    unittest.main()
