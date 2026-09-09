"""Download a selected book from a user-configured source.

The catalogue used by the Books tab and the download source are deliberately
separate.  The source is read from ``book_download_source`` (or the shorter
``book_source_url`` alias) in the user's settings.json.  It may be a URL or an
object with ``base_url``, ``detail_url`` and ``output_dir``.  The search route
is fixed to the compact index.php query shape used by the supported source
format, so it is not another setting users need to maintain.

The implementation follows the small, dependency-free flow used by the
reference script: search an HTML page, follow the best matching entry, find a
download anchor, and stream it to a temporary file before atomically moving it
into the output directory.  No catalogue hostname is embedded here.
"""
import html
import json
import mimetypes
import os
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from http.cookiejar import CookieJar

import settings


DOWNLOAD_EXTENSIONS = {
    '.azw', '.azw3', '.cb7', '.cbr', '.cbz', '.djvu', '.epub', '.fb2',
    '.mobi', '.pdf', '.rtf', '.txt', '.zip',
}
_DEFAULT_OUTPUT = Path.home() / 'Downloads' / 'Yoink' / 'Books'


def _clean(value):
    return re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()


def describe_error(error, url=''):
    """Turn source/network errors into a useful message for the popup."""
    code = getattr(error, 'code', None)
    path = urlsplit(url).path if url else ''
    if code:
        return f'Book source returned HTTP {code}' + (f' for {path}.' if path else '.') + ' Check the source address.'
    if isinstance(error, (TimeoutError, URLError)):
        return 'The configured book source could not be reached. Check its address and connection.'
    message = _clean(error)
    return message or 'The configured book source failed.'


def _safe_url(value, *, base=''):
    value = str(value or '').strip()
    if not value:
        return ''
    if value.startswith('/') and base:
        value = urljoin(base.rstrip('/') + '/', value.lstrip('/'))
    elif not urlsplit(value).scheme and base:
        value = urljoin(base.rstrip('/') + '/', value)
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https', 'file'):
        raise ValueError('Book source URLs must use http://, https://, or file://.')
    if parsed.scheme in ('http', 'https') and not parsed.netloc:
        raise ValueError('Book source URL is missing a host.')
    if parsed.username or parsed.password:
        raise ValueError('Book source URLs cannot contain embedded credentials.')
    return value


def _source_config():
    data = settings.load()
    raw = data.get('book_download_source')
    if raw in (None, ''):
        raw = data.get('book_source_url')
    if raw in (None, ''):
        raw = data.get('book_download_base_url')
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise ValueError('Set book_download_source in ~/.config/yoink/settings.json first.')
        config = {'base_url': raw}
    elif isinstance(raw, dict):
        config = dict(raw)
    else:
        raise ValueError('Set book_download_source in ~/.config/yoink/settings.json first.')

    base = str(config.get('base_url') or config.get('url') or '').strip()
    # Accept a previously documented full search URL as a source address too.
    # The route and query parameters are still discarded in favour of the
    # fixed implementation below; only its origin is retained.
    if base and ('{query}' in base or '{title}' in base or urlsplit(base).query):
        parsed = urlsplit(base)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            base = f'{parsed.scheme}://{parsed.netloc}'
        elif parsed.scheme == 'file':
            base = parsed._replace(query='', fragment='').geturl()
    if base.startswith('/') or base.startswith('~'):
        base = Path(base).expanduser().resolve().as_uri()
    base = _safe_url(base)
    if not base:
        raise ValueError('book_download_source needs a base_url.')
    if base.startswith('file:') and not base.endswith('/'):
        base += '/'
    config['base_url'] = base
    return config


def _values(book, config):
    title = _clean(book.get('title') or book.get('name'))
    author = _clean(book.get('author'))
    return {
        'base_url': config['base_url'].rstrip('/'),
        'query': quote(title),
        'title': quote(title),
        'author': quote(author),
        'id': quote(str(book.get('id') or '')),
        'md5': quote(str(book.get('md5') or '')),
        'extension': quote(str(book.get('extension') or '').lstrip('.')),
    }


def _render_url(template, book, config):
    template = str(template or '').strip()
    if not template:
        return ''
    try:
        rendered = template.format(**_values(book, config))
    except (KeyError, ValueError) as error:
        raise ValueError(f'Invalid book source URL template: {error}') from error
    return _safe_url(rendered, base=config['base_url'])


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'a' or self._current is not None:
            return
        values = dict(attrs)
        self._current = {'href': values.get('href', ''), 'parts': []}

    def handle_data(self, data):
        if self._current is not None:
            self._current['parts'].append(data)

    def handle_endtag(self, tag):
        if tag.lower() != 'a' or self._current is None:
            return
        current = self._current
        current['text'] = _clean(' '.join(current.pop('parts')))
        self.anchors.append(current)
        self._current = None


class _SourceClient:
    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def open(self, url, *, referer='', timeout=20):
        request = Request(url, headers={
            'User-Agent': 'Yoink/0.4',
            'Accept': 'text/html,application/xhtml+xml,application/octet-stream,*/*',
        })
        if referer:
            request.add_header('Referer', referer)
        return self.opener.open(request, timeout=timeout)

    def html(self, url, *, referer=''):
        with self.open(url, referer=referer) as response:
            return response.read().decode('utf-8', 'ignore')


def _normalise(value):
    return re.sub(r'[^a-z0-9]+', ' ', _clean(value).casefold()).strip()


def _is_direct_link(href, text=''):
    path = urlsplit(href).path.casefold()
    extension = Path(path).suffix
    return extension in DOWNLOAD_EXTENSIONS or bool(re.search(r'\b(download|get(?: file)?|direct)\b', f'{href} {text}', re.IGNORECASE))


def _match_score(query, author, anchor):
    query_text = _normalise(query)
    candidate = _normalise(f"{anchor.get('text', '')} {anchor.get('href', '')}")
    if not query_text or not candidate:
        return 0
    score = 0
    if query_text in _normalise(anchor.get('text', '')):
        score += 100
    elif query_text in candidate:
        score += 70
    query_tokens = set(query_text.split())
    candidate_tokens = set(candidate.split())
    score += len(query_tokens & candidate_tokens) * 8
    author_text = _normalise(author)
    if author_text and author_text in candidate:
        score += 20
    return score


def _selected_source_url(book, config):
    """Use a selected catalogue URL when it belongs to this source."""
    value = _clean(book.get('url') or book.get('source_url'))
    if not value:
        return ''
    try:
        selected = _safe_url(value, base=config['base_url'])
    except ValueError:
        return ''
    selected_parts = urlsplit(selected)
    base_parts = urlsplit(config['base_url'])
    if selected_parts.scheme != base_parts.scheme or selected_parts.netloc != base_parts.netloc:
        return ''
    return selected


def _search_url(config, book):
    # This is the compact HTML search shape used by many small catalogue
    # sites.  It is a path template only; the hostname always comes from the
    # user's configured source.
    return _safe_url(config['base_url'].rstrip('/') + '/index.php?req=' + _values(book, config)['query']
                     + '&open=0&res=25&view=simple&phrase=1&column=def')


def _search_urls(config, book):
    return [_search_url(config, book)]


def _find_matches(markup, book, config):
    parser = _AnchorParser()
    parser.feed(markup)
    query = _clean(book.get('title') or book.get('name'))
    author = _clean(book.get('author'))
    matches = []
    direct = []
    opaque_entries = []
    for anchor in parser.anchors:
        href = _clean(anchor.get('href'))
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        try:
            absolute = _safe_url(urljoin(config['base_url'].rstrip('/') + '/', href.lstrip('/')),
                                base=config['base_url'])
        except ValueError:
            # Search pages often contain unrelated donation/upload links with
            # ftp:, bitcoin:, or other schemes.  They are not source entries.
            continue
        path = urlsplit(absolute).path.casefold()
        if path.endswith('/index.php') or path.endswith('/setlang.php'):
            continue
        anchor['url'] = absolute
        score = _match_score(query, author, anchor)
        if score:
            matches.append((score + (10 if _is_direct_link(absolute, anchor.get('text')) else 0), anchor))
        if _is_direct_link(absolute, anchor.get('text')):
            direct.append(anchor)
        # Some catalogue pages intentionally expose only an opaque entry id
        # (for example a hash in the query string).  The search query has
        # already narrowed the page, so retain those entries in source order
        # when no title-bearing anchors are available.
        if re.search(r'(?:[?&](?:id|key|hash|token|md5)=)[^&\s]+', absolute, re.IGNORECASE):
            opaque_entries.append(anchor)
    matches.sort(key=lambda value: value[0], reverse=True)
    # A source may use a generic "Download" link with the title in a nearby
    # card rather than inside the anchor itself.  Keep direct links as a
    # conservative fallback when there is only one obvious file.
    ordered = [anchor for _, anchor in matches]
    if not ordered and len(direct) == 1:
        ordered = direct
    if not ordered and opaque_entries:
        ordered = opaque_entries
    seen = set()
    return [anchor for anchor in ordered if not (anchor['url'] in seen or seen.add(anchor['url']))]


def _find_download_links(markup, page_url, book, config):
    parser = _AnchorParser()
    parser.feed(markup)
    query = _clean(book.get('title') or book.get('name'))
    links = []
    for anchor in parser.anchors:
        href = _clean(anchor.get('href'))
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        try:
            absolute = _safe_url(urljoin(page_url, href))
        except ValueError:
            continue
        if not _is_direct_link(absolute, anchor.get('text')):
            continue
        score = 100 if re.search(r'\b(download|get|direct)\b', f"{anchor.get('text', '')} {href}", re.IGNORECASE) else 20
        score += _match_score(query, '', anchor)
        links.append((score, absolute))
    links.sort(key=lambda value: value[0], reverse=True)
    seen = set()
    return [url for _, url in links if not (url in seen or seen.add(url))]


def _find_entry_links(markup, page_url, config):
    """Find session-aware intermediate pages such as ``ads.php?md5=...``."""
    parser = _AnchorParser()
    parser.feed(markup)
    links = []
    for anchor in parser.anchors:
        href = _clean(anchor.get('href'))
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        try:
            absolute = _safe_url(urljoin(page_url, href))
        except ValueError:
            continue
        path = urlsplit(absolute).path.casefold()
        if not path.endswith('/ads.php'):
            continue
        if not re.search(r'(?:[?&]md5=)[^&\s]+', absolute, re.IGNORECASE):
            continue
        links.append(absolute)
    seen = set()
    return [url for url in links if not (url in seen or seen.add(url))]


def _filename(response, url, book):
    disposition = response.headers.get('Content-Disposition', '')
    name = ''
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
    if match:
        name = unquote(match.group(1).strip().strip('"'))
    if not name:
        match = re.search(r'filename\s*=\s*"?([^";]+)', disposition, re.IGNORECASE)
        if match:
            name = unquote(match.group(1).strip())
    if not name:
        name = unquote(Path(urlsplit(url).path).name)
    title = _clean(book.get('title') or book.get('name')) or 'book'
    name = name or title
    name = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', '_', name).strip(' .')
    if not name:
        name = title
    if not Path(name).suffix:
        extension = str(book.get('extension') or '').strip().lstrip('.').lower()
        content_type = (response.headers.get_content_type() if response.headers else '')
        extension = extension or (mimetypes.guess_extension(content_type) or '').lstrip('.')
        if extension:
            name += '.' + extension
    return name[:180]


def _stream_to_file(client, url, output_dir, book, referer=''):
    output_dir.mkdir(parents=True, exist_ok=True)
    with client.open(url, referer=referer, timeout=60) as response:
        filename = _filename(response, url, book)
        target = output_dir / filename
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.part', dir=output_dir)
        temporary_path = Path(temporary)
        total_header = response.headers.get('Content-Length') if response.headers else None
        try:
            total = max(0, int(total_header or 0))
        except ValueError:
            total = 0
        done = 0
        print('PROGRESS:' + json.dumps({'done': 0, 'total': total or 1}), flush=True)
        try:
            with os.fdopen(fd, 'wb') as output:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    output.write(chunk)
                    done += len(chunk)
                    print('PROGRESS:' + json.dumps({'done': done, 'total': total or done}), flush=True)
                output.flush()
                os.fsync(output.fileno())
            if done <= 0:
                raise RuntimeError('The source returned an empty file.')
            os.replace(temporary_path, target)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    return {'ok': True, 'path': str(target), 'url': url, 'source': _safe_url(url)}


def download(book, options=None):
    """Find and download one book from the configured source."""
    if not isinstance(book, dict):
        raise ValueError('Select a book before downloading.')
    title = _clean(book.get('title') or book.get('name'))
    if not title:
        raise ValueError('The selected book has no title.')
    config = _source_config()
    client = _SourceClient()
    detail_template = config.get('detail_url') or config.get('book_url')
    if detail_template:
        detail_url = _render_url(detail_template, book, config)
        matches = [{'url': detail_url, 'text': title}]
        search_url = detail_url
    elif _selected_source_url(book, config):
        # The Books catalogue already gives us the exact edition URL.  Using
        # it avoids a second title search and prevents navigation links from
        # being mistaken for the selected edition.
        detail_url = _selected_source_url(book, config)
        matches = [{'url': detail_url, 'text': title}]
        search_url = detail_url
    else:
        search_url = ''
        search_markup = ''
        search_error = None
        candidates = _search_urls(config, book)
        for candidate in candidates:
            try:
                search_markup = client.html(candidate)
                search_url = candidate
                break
            except HTTPError as error:
                search_error = error
                break
            except Exception as error:
                search_error = error
                break
        if not search_markup:
            raise RuntimeError(describe_error(search_error, search_url or _search_url(config, book))) from search_error
        matches = _find_matches(search_markup, book, config)
    if not matches:
        raise RuntimeError('No matching book was found on the configured source.')

    explicit_download = config.get('download_url') or config.get('file_url')
    output_value = (options or {}).get('output') or config.get('output_dir') or str(_DEFAULT_OUTPUT)
    output_dir = Path(str(output_value)).expanduser().absolute()
    errors = []
    try:
        max_results = max(1, min(10, int(config.get('max_results', 3))))
    except (TypeError, ValueError):
        max_results = 3
    for match in matches[:max_results]:
        page_url = match['url']
        links = []
        if explicit_download:
            links.append(_render_url(explicit_download, book, config))
        elif _is_direct_link(page_url, match.get('text')):
            links.append(page_url)
        else:
            try:
                detail_markup = client.html(page_url, referer=search_url)
                links = _find_download_links(detail_markup, page_url, book, config)
                # Prefer the source's session-aware entry page over a direct
                # TOR or mirror URL listed alongside it.  The entry request
                # sets cookies and exposes the usable get.php URL.
                entry_links = _find_entry_links(detail_markup, page_url, config)
                if entry_links:
                    session_links = []
                    for entry_url in entry_links[:max_results]:
                        try:
                            entry_markup = client.html(entry_url, referer=page_url)
                            session_links.extend(_find_download_links(entry_markup, entry_url, book, config))
                        except Exception as error:
                            errors.append(error)
                    if session_links:
                        links = session_links
            except Exception as error:
                errors.append(error)
                continue
        for link in links:
            try:
                return _stream_to_file(client, link, output_dir, book, referer=page_url)
            except Exception as error:
                errors.append(error)
    if errors:
        raise RuntimeError(describe_error(errors[-1], page_url)) from errors[-1]
    raise RuntimeError('No download link was found for the selected book.')
