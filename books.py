"""Read-only Library Genesis book catalogue client.

The Books tab only reads public catalogue and edition metadata.  It does not
download files or resolve file-host links.  The HTML endpoint is used instead
of a third-party package so the plugin keeps the same small runtime footprint
as the Games tab.
"""
import html
import re
import time
from html.parser import HTMLParser
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


PAGE_SIZE = 18
# A larger page lets the default English filter fill one UI page without
# making a series of sequential mirror requests.
RESULT_SIZE = 100
LIBGEN_MIRRORS = (
    'https://libgen.li',
    'https://libgen.vg',
    'https://libgen.la',
)
_LIST_CACHE = {}
_DETAIL_CACHE = {}
_CACHE_TTL = 300


def _clean(value):
    value = html.unescape(str(value or ''))
    return re.sub(r'\s+', ' ', value).strip()


def _strip_tags(value):
    return _clean(re.sub(r'<[^>]+>', ' ', value or ''))


class _ResultsParser(HTMLParser):
    """Collect rows and cells from LibGen's result table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_results = False
        self.rows = []
        self.row = None
        self.cell = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and attrs.get('id') == 'tablelibgen':
            self.in_results = True
            return
        if not self.in_results:
            return
        if tag == 'tr':
            self.row = []
        elif tag == 'td' and self.row is not None and self.cell is None:
            self.cell = {'parts': [], 'anchors': []}
        elif tag == 'a' and self.cell is not None and self.anchor is None:
            self.anchor = {'href': attrs.get('href', ''), 'title': attrs.get('title', ''), 'parts': []}
            self.cell['anchors'].append(self.anchor)

    def handle_endtag(self, tag):
        if not self.in_results:
            return
        if tag == 'a' and self.anchor is not None:
            self.anchor = None
        elif tag == 'td' and self.cell is not None:
            self.cell['text'] = _clean(' '.join(self.cell.pop('parts')))
            for anchor in self.cell['anchors']:
                anchor['text'] = _clean(' '.join(anchor.pop('parts')))
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            self.in_results = False

    def handle_data(self, data):
        if not self.in_results or self.cell is None:
            return
        self.cell['parts'].append(data)
        if self.anchor is not None:
            self.anchor['parts'].append(data)


def _request(url, timeout=12):
    request = Request(url, headers={
        'User-Agent': 'Yoink/0.4',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode('utf-8', 'ignore')


def _fetch(path):
    """Fetch a page, trying the current mirror and two alternatives."""
    errors = []
    for mirror in LIBGEN_MIRRORS:
        try:
            return mirror, _request(urljoin(mirror + '/', path.lstrip('/')))
        except Exception as error:
            errors.append(error)
    raise RuntimeError('Library Genesis is unavailable.') from (errors[-1] if errors else None)


def _query_path(query='', page=1):
    params = [
        ('req', query),
        ('columns[]', 't'), ('columns[]', 'a'), ('columns[]', 's'),
        ('columns[]', 'y'), ('columns[]', 'p'), ('columns[]', 'i'),
        ('objects[]', 'f'), ('objects[]', 'e'),
        ('topics[]', 'l'), ('topics[]', 'f'),
        ('res', str(RESULT_SIZE)), ('covers', '1'), ('curtab', 'f'),
        ('page', str(max(1, int(page)))),
    ]
    return 'index.php?' + urlencode(params)


def _first_anchor(cell, pattern):
    for anchor in cell.get('anchors', []):
        if re.search(pattern, anchor.get('href', ''), re.IGNORECASE):
            return anchor
    return {}


def _isbn(text):
    # ISBN-10/13 values are commonly printed in the first cell below the
    # edition title.  Keep only digits and X, then validate the length.
    patterns = (
        r'(?<!\d)97[89](?:[- ]?\d){10}(?!\d)',
        r'(?<!\d)(?:\d[- ]?){9}[\dXx](?!\d)',
    )
    for pattern in patterns:
        for candidate in re.findall(pattern, text or ''):
            value = re.sub(r'[^0-9Xx]', '', candidate).upper()
            if len(value) in (10, 13):
                return value
    return ''


def _row_text(row):
    """Return all visible row text for metadata that moves between columns."""
    return ' '.join(cell.get('text', '') for cell in row or [])


def _md5(row):
    for cell in row:
        for anchor in cell.get('anchors', []):
            match = re.search(r'(?:[?&]md5=)([0-9a-f]{32})', anchor.get('href', ''), re.IGNORECASE)
            if match:
                return match.group(1).lower()
    return ''


def _file_id(row):
    # Different LibGen mirrors place the numeric file id in different cells.
    # Search all cells instead of assuming it is next to the title.
    for cell in row:
        match = re.search(r'\b[a-z]\s+(\d{6,})\b', cell.get('text', ''), re.IGNORECASE)
        if match:
            return match.group(1)
        for anchor in cell.get('anchors', []):
            match = re.search(r'ID:\s*(\d+)', anchor.get('title', ''), re.IGNORECASE)
            if match:
                return match.group(1)
    return ''


def _cover_urls(row, md5, mirror):
    """Return the LibGen cover first, with Open Library as a fallback."""
    isbn = _isbn(_row_text(row))
    fallbacks = []
    if isbn:
        # Open Library is a keyless fallback when a LibGen image is absent.
        fallbacks.append('https://covers.openlibrary.org/isbn/' + isbn + '-M.jpg?default=false')
    if not md5:
        return fallbacks
    file_id = _file_id(row)
    if file_id:
        bucket = (int(file_id) // 1000) * 1000
        topic = _topic(row)
        folders = ('fictioncovers', 'covers') if topic == 'f' else ('covers', 'fictioncovers')
        mirrors = [mirror] + [candidate for candidate in LIBGEN_MIRRORS if candidate != mirror]
        rendered = []
        for source_mirror in mirrors:
            for folder in folders:
                source = source_mirror.rstrip('/') + '/' + folder + '/' + str(bucket) + '/' + md5 + '.jpg'
                # LibGen requires a referrer for image requests.  QML cannot
                # attach one to Image, so use a stateless image proxy while
                # preserving the original LibGen URL as the upstream source.
                url = 'https://images.weserv.nl/?url=' + quote(source.removeprefix('https://'), safe='')
                if url not in rendered:
                    rendered.append(url)
        return rendered + fallbacks
    return fallbacks


def _topic(row):
    for cell in row[:1]:
        match = re.search(r'\b([a-z])\s+\d{6,}\b', cell.get('text', ''), re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return 'l'


def _book_from_row(row, mirror):
    if len(row) < 8:
        return None
    title_anchor = _first_anchor(row[0], r'(?:^|/)edition\.php(?:\?|$)')
    if not title_anchor:
        return None
    raw_title = _clean(title_anchor.get('text', ''))
    file_count = 1
    suffix = re.search(r'\s+(First|Second|Third|\d+)$', raw_title, re.IGNORECASE)
    if suffix and suffix.group(1).isdigit():
        file_count = max(1, int(suffix.group(1)))
    title = raw_title
    # LibGen appends the number of files in an edition as an italic suffix
    # (for example ``<i>First</i>`` or ``<i>2</i>``) inside the title anchor.
    title = re.sub(r'\s+(?:First|Second|Third|\d+)$', '', title, flags=re.IGNORECASE)
    if not title:
        return None
    md5 = _md5(row)
    edition_id = re.search(r'[?&]id=(\d+)', title_anchor.get('href', ''))
    if not edition_id:
        return None
    def cell(index):
        return _clean(row[index].get('text', '')) if index < len(row) else ''
    year = re.search(r'\b(?:18|19|20)\d{2}\b', cell(3))
    cover_urls = _cover_urls(row, md5, mirror)
    mirror_count = sum(1 for cell_data in row for anchor in cell_data.get('anchors', [])
                       if re.search(r'(?:[?&]md5=|/book/)', anchor.get('href', ''), re.IGNORECASE))
    return {
        'id': edition_id.group(1),
        'name': title,
        'title': title,
        'author': cell(1) or 'Unknown author',
        'publisher': cell(2),
        'year': year.group(0) if year else cell(3),
        'language': cell(4),
        'pages': cell(5),
        'size': cell(6),
        'extension': cell(7).lower(),
        'md5': md5,
        # LibGen does not publish a popularity score.  Mirror and file counts
        # are the closest public availability signals, so use them as a
        # stable popularity proxy for result ordering.
        'popularity': mirror_count * 100 + file_count,
        'mirrors': mirror_count,
        'cover': cover_urls[0] if cover_urls else '',
        'coverFallbacks': cover_urls[1:],
        'url': urljoin(mirror + '/', title_anchor.get('href', '')),
        'source': 'libgen',
        'summary': ' · '.join(value for value in (cell(1), cell(2), cell(3), cell(4), cell(5), cell(6), cell(7)) if value) or 'No metadata available.',
    }


def _parse_results(markup, mirror):
    parser = _ResultsParser()
    parser.feed(markup)
    results = []
    seen = set()
    for row in parser.rows:
        book = _book_from_row(row, mirror)
        if book and book['id'] not in seen:
            seen.add(book['id'])
            # Keep LibGen's relevance order as the final tie-breaker.  This
            # is useful when several editions expose the same number of
            # mirrors and files.
            book['_catalogue_order'] = len(results)
            results.append(book)
    results.sort(key=lambda book: (-book.get('popularity', 0), book.get('_catalogue_order', 0)))
    for book in results:
        book.pop('_catalogue_order', None)
    return results


def _list_page(query='', page=1):
    key = (query.strip().lower(), max(1, int(page)))
    cached = _LIST_CACHE.get(key)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    mirror, markup = _fetch(_query_path(query, page))
    results = _parse_results(markup, mirror)
    paginator = re.search(r'new Paginator\([^,]+,\s*(\d+),\s*(\d+),\s*(\d+)', markup)
    if paginator:
        total = int(paginator.group(1))
        page_number = int(paginator.group(2))
        page_size = int(paginator.group(3))
        has_more = total > page_number * page_size
    else:
        # A mirror can omit the paginator script.  A full response is still
        # evidence that another source page may exist; a short response is
        # the reliable end-of-catalogue signal in that case.
        has_more = len(results) >= RESULT_SIZE
    _LIST_CACHE[key] = (now, (results, has_more))
    return results, has_more


def _list(query='', page=1, language='English'):
    """Return one search page, filtering by language across source pages."""
    page = max(1, int(page))
    language = str(language or 'English').strip()
    if not language or language.casefold() in ('all', 'any'):
        start = (page - 1) * PAGE_SIZE
        source_page = start // RESULT_SIZE + 1
        rows, _ = _list_page(query, source_page)
        offset = start % RESULT_SIZE
        return rows[offset:offset + PAGE_SIZE]

    target = language.casefold()
    filtered = []
    source_page = 1
    # LibGen does not expose a stable language query parameter.  Walk its
    # public pages until enough entries are collected for the requested UI
    # page, while the five-minute page cache prevents repeat requests.
    while len(filtered) < page * PAGE_SIZE and source_page <= page * 8:
        rows, _ = _list_page(query, source_page)
        if not rows:
            break
        filtered.extend(book for book in rows if target in (book.get('language') or '').casefold())
        if len(rows) < RESULT_SIZE:
            break
        source_page += 1
    start = (page - 1) * PAGE_SIZE
    return filtered[start:start + PAGE_SIZE]


def search_page(query, page=1, language='English'):
    """Return search results and whether another filtered page exists."""
    query = str(query or '').strip()
    if not query:
        raise ValueError('Enter a book title or author.')
    page = max(1, int(page))
    language = str(language or 'English').strip()
    if not language or language.casefold() in ('all', 'any'):
        start = (page - 1) * PAGE_SIZE
        source_page = start // RESULT_SIZE + 1
        rows, source_more = _list_page(query, source_page)
        offset = start % RESULT_SIZE
        items = rows[offset:offset + PAGE_SIZE]
        # Several UI pages are packed into each LibGen request.  A next page
        # exists when there are still rows in this response, or when the
        # source paginator reports another response page.
        has_next = offset + len(items) < len(rows) or source_more
        return {'items': items, 'has_next': has_next}

    target = language.casefold()
    filtered = []
    source_page = 1
    source_more = True
    needed = page * PAGE_SIZE
    while len(filtered) <= needed and source_page <= page * 8:
        rows, source_more = _list_page(query, source_page)
        filtered.extend(book for book in rows if target in (book.get('language') or '').casefold())
        if not rows or not source_more:
            break
        source_page += 1
    start = (page - 1) * PAGE_SIZE
    return {'items': filtered[start:start + PAGE_SIZE], 'has_next': len(filtered) > start + PAGE_SIZE}


def search(query, page=1, language='English'):
    query = str(query or '').strip()
    if not query:
        raise ValueError('Enter a book title or author.')
    return _list(query=query, page=page, language=language)


def _detail_field(markup, label):
    match = re.search(r'<strong>\s*' + re.escape(label) + r':\s*</strong>\s*(.*?)</p>', markup, re.IGNORECASE | re.DOTALL)
    return _strip_tags(match.group(1)) if match else ''


def _detail_inline_field(markup, label):
    match = re.search(r'<strong>\s*' + re.escape(label) + r':\s*</strong>\s*(?:<nobr>)?\s*([^<]+)', markup, re.IGNORECASE)
    return _clean(match.group(1)) if match else ''


def detail(book_id):
    value = str(book_id or '').strip()
    if not value.isdigit():
        raise ValueError('Invalid book entry.')
    cached = _DETAIL_CACHE.get(value)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    mirror, markup = _fetch('edition.php?id=' + value)
    cover_match = re.search(r'<img[^>]+src=["\']([^"\']*/(?:covers|fictioncovers|comicscovers|magcovers)/[^"\']+?\.jpg)["\']', markup, re.IGNORECASE)
    title = _detail_field(markup, 'Title')
    author = _detail_field(markup, 'Author(s)')
    cover = urljoin(mirror + '/', cover_match.group(1)) if cover_match else ''
    rendered_cover = ('https://images.weserv.nl/?url=' + quote(cover.removeprefix('https://'), safe='')) if cover else ''
    language = _detail_field(markup, 'Language')
    pages = _detail_inline_field(markup, 'Pages')
    size = _detail_inline_field(markup, 'Size')
    extension = _detail_inline_field(markup, 'Extension').lower()
    result = {
        'id': value,
        'name': title or 'Book details',
        'title': title or 'Book details',
        'author': author or 'Unknown author',
        'publisher': _detail_field(markup, 'Publisher'),
        'year': _detail_field(markup, 'Year'),
        'language': language,
        'pages': pages,
        'size': size,
        'extension': extension,
        'cover': rendered_cover,
        'coverFallbacks': [],
        'url': urljoin(mirror + '/', 'edition.php?id=' + value),
        'source': 'libgen',
        'summary': ' · '.join(value for value in (_detail_field(markup, 'Publisher'), _detail_field(markup, 'Year'), language, pages, size, extension) if value) or 'No additional metadata available.',
    }
    _DETAIL_CACHE[value] = (now, result)
    return result
