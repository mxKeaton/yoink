"""Small, read-only game catalogue client.

IGDB is used when credentials are configured. Steam's public store endpoints
provide a useful fallback, so browsing works without an account or API key.
Download controls intentionally remain placeholders.
"""
import json
import html
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, quote_plus, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import settings

PAGE_SIZE = 18
_STEAM_DETAILS_CACHE = {}
_STEAM_DETAILS_CACHE_TTL = 300
_STEAM_DETAILS_SUCCESS_TTL = 3600
_SOURCE_REQUEST_TIMEOUT = 2.0
_STORE_LOOKUP_CACHE = {}
_STORE_LOOKUP_CACHE_TTL = 300
_STORE_REQUEST_TIMEOUT = 2.5


def _steam_detail(appid):
    """Return one Steam appdetails payload, using the short-lived cache."""
    appid = str(appid)
    now = time.time()
    cached = _STEAM_DETAILS_CACHE.get(appid)
    if cached:
        stamp, data, success = cached
        ttl = _STEAM_DETAILS_SUCCESS_TTL if success else _STEAM_DETAILS_CACHE_TTL
        if now - stamp < ttl:
            return data
    try:
        payload = _json('https://store.steampowered.com/api/appdetails?appids=' + appid + '&l=en')
        entry = payload.get(appid, {}) if isinstance(payload, dict) else {}
        data = entry.get('data', {}) if isinstance(entry, dict) and entry.get('success', True) else {}
        success = bool(data)
    except Exception:
        data, success = {}, False
    _STEAM_DETAILS_CACHE[appid] = (now, data if isinstance(data, dict) else {}, success)
    return _STEAM_DETAILS_CACHE[appid][1]

def source_urls():
    saved = settings.load()

    def read_list(value):
        try:
            value = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            value = []
        return value if isinstance(value, list) else []

    # game_always_checked_urls is intentionally consumed only here. It can be
    # maintained directly in settings.json while remaining absent from the
    # Games configuration controls.
    predefined = [str(value).strip() for value in read_list(saved.get('game_always_checked_urls', []))]
    configured = []
    combined = []
    for value in predefined + configured:
        value = value.rstrip('/')
        if value.startswith(('http://', 'https://')) and value not in combined:
            combined.append(value)
    return combined

def source_matches(name):
    """Return configured sites whose direct game route can be opened.

    Each configured source gets one short direct request. A timeout remains
    visible so the user can still try the route in their normal browser
    session; HTTP errors and known error pages stay hidden.
    """
    slug = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')
    if not slug:
        return []

    def candidates(base):
        encoded_title = quote_plus(str(name).lower())
        host = base.lower()
        if 'steamrip.com' in host:
            return (urljoin(base + '/', slug + '-free-download/'),)
        if 'ankergames.net' in host:
            return (urljoin(base + '/game/', slug),)
        if 'astralgames.net' in host:
            return (urljoin(base + '/game/', slug),)
        return (urljoin(base + '/', slug), urljoin(base + '/', encoded_title),
                urljoin(base + '/game/', slug), urljoin(base + '/games/', slug))

    def check(base):
        possible_urls = candidates(base)
        match_url = possible_urls[0]
        valid = False
        timed_out = False
        for url in possible_urls:
            try:
                request = Request(url, headers={'User-Agent': 'Yoink/0.4'})
                with urlopen(request, timeout=_SOURCE_REQUEST_TIMEOUT) as response:
                    final_url = response.geturl() or url
                    body = response.read(65536).decode('utf-8', 'ignore').lower()
                    final_path = urlparse(final_url).path.rstrip('/').lower()
                    if response.status in (408, 504, 524):
                        timed_out = True
                        continue
                    error_url = (final_path in ('', '/') or any(token in final_path for token in ('/error', '/404', 'not-found', 'page-not-found')))
                    error_body = any(token in body for token in (
                        'page not found', '404 not found', 'error occurred', 'does not exist',
                        'just a moment', 'enable javascript and cookies', 'cf-chl-'))
                    if 200 <= response.status < 400 and not error_url and not error_body:
                        match_url, valid = final_url, True
                        break
            except HTTPError as error:
                if getattr(error, 'code', None) in (408, 504, 524):
                    timed_out = True
                continue
            except (socket.timeout, TimeoutError):
                timed_out = True
                continue
            except URLError as error:
                reason = getattr(error, 'reason', None)
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    timed_out = True
                continue
            except Exception:
                continue
        return {'base': base, 'url': match_url, 'valid': valid, 'timeout': not valid and timed_out}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, source_urls()))
    # Do not expose guessed error routes as clickable source buttons. Timeout
    # entries are deliberately retained so the browser can try the source.
    return [result for result in results if result['valid'] or result['timeout']]


def source_links(name):
    """Return only configured game sources with a validated page URL."""
    return source_matches(name)


def _store_title(value):
    return re.sub(r'[^a-z0-9]+', ' ', html.unescape(str(value or '')).lower()).strip()


def _store_slug_matches(name, value):
    expected = _store_title(name).split()
    actual = _store_title(value).split()
    return bool(expected) and all(token in actual for token in expected)


def _store_context_matches(name, context):
    expected = _store_title(name)
    if not expected:
        return False
    context = html.unescape(context.replace('\\/', '/'))
    for match in re.finditer(r'"(?:name|title|displayName)"\s*:\s*"((?:\\.|[^"\\])*)"', context, re.IGNORECASE):
        value = match.group(1).replace('\\"', '"')
        if expected in _store_title(value):
            return True
    for fragment in re.findall(r'>\s*([^<>]{2,160})\s*<', context):
        if expected in _store_title(fragment):
            return True
    return False


def _store_records(value):
    if isinstance(value, dict):
        if any(key in value for key in ('title', 'name', 'displayName', 'productName', 'productSlug', 'urlSlug', 'slug', 'storeLink')):
            yield value
        for nested in value.values():
            yield from _store_records(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _store_records(nested)


def _store_record_matches(name, record):
    expected = _store_title(name)
    for key in ('title', 'name', 'displayName', 'productName'):
        value = record.get(key)
        if isinstance(value, str) and expected and expected in _store_title(value):
            return True
    return False


def _gog_record_url(record):
    for key in ('storeLink', 'productUrl', 'url', 'link'):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            continue
        candidate = urljoin('https://www.gog.com/', value)
        parsed = urlparse(candidate)
        if parsed.netloc.lower().endswith('gog.com') and '/game/' in parsed.path.lower():
            return candidate
    for key in ('productSlug', 'urlSlug', 'slug'):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            continue
        slug = value.strip('/')
        if not slug or '/' in slug or slug.startswith(('http:', 'https:')):
            continue
        return 'https://www.gog.com/en/game/' + quote(slug, safe='_-.')
    return ''


def _gog_api_lookup(name, api_url):
    """Return (reachable, matching product URL) for the GoG catalog API."""
    try:
        request = Request(api_url, headers={'User-Agent': 'Yoink/0.4', 'Accept': 'application/json'})
        with urlopen(request, timeout=_STORE_REQUEST_TIMEOUT) as response:
            if not 200 <= response.status < 400:
                return False, ''
            payload = json.loads(response.read(262144).decode('utf-8', 'ignore'))
        for record in _store_records(payload):
            if _store_record_matches(name, record):
                product_url = _gog_record_url(record)
                if product_url:
                    return True, product_url
        return True, ''
    except Exception:
        return False, ''


def _gog_product_url(name, body, search_url):
    body = body.replace('\\/', '/')
    pattern = r'''(?:(?:https?:)?//(?:www\.)?gog\.com)?/(?:[a-z]{2}/)?game/[^\"'<>\s]+'''
    for match in re.finditer(pattern, body, re.IGNORECASE):
        candidate = html.unescape(match.group(0)).rstrip('.,;)')
        candidate = urljoin(search_url, candidate)
        parsed = urlparse(candidate)
        if not parsed.netloc.lower().endswith('gog.com'):
            continue
        path_parts = [part for part in parsed.path.split('/') if part]
        slug = path_parts[-1] if path_parts else ''
        context = body[max(0, match.start() - 900):match.end() + 900]
        if _store_slug_matches(name, slug) or _store_context_matches(name, context):
            return candidate
    return ''


def store_links(name):
    """Return a direct GoG product page when its catalog matches a title."""
    title = str(name or '').strip()
    key = title.lower()
    now = time.time()
    cached = _STORE_LOOKUP_CACHE.get(key)
    if cached and now - cached[0] < _STORE_LOOKUP_CACHE_TTL:
        return list(cached[1])
    query = quote_plus(title)
    search_url = 'https://www.gog.com/en/games?query=' + query
    api_url = 'https://catalog.gog.com/v1/catalog?query=like%3A' + quote(title, safe='') + '&limit=20&productType=in%3Agame%2Cpack&countryCode=US&locale=en-US&currencyCode=USD'
    api_reachable, product_url = _gog_api_lookup(title, api_url)
    if api_reachable:
        matches = [{'id': 'gog', 'url': product_url, 'valid': True}] if product_url else []
    else:
        matches = []
        try:
            request = Request(search_url, headers={'User-Agent': 'Yoink/0.4'})
            with urlopen(request, timeout=_STORE_REQUEST_TIMEOUT) as response:
                final_url = response.geturl() or search_url
                body = response.read(131072).decode('utf-8', 'ignore')
                final_path = urlparse(final_url).path.rstrip('/').lower()
                error_page = final_path in ('', '/') or any(token in final_path for token in ('/error', '/404', 'not-found', 'page-not-found'))
                error_body = any(token in body.lower() for token in ('page not found', '404 not found', 'error occurred', 'does not exist'))
                if 200 <= response.status < 400 and not error_page and not error_body:
                    product_url = _gog_product_url(title, body, final_url)
                    if product_url:
                        matches = [{'id': 'gog', 'url': product_url, 'valid': True}]
        except Exception:
            pass
    _STORE_LOOKUP_CACHE[key] = (now, matches)
    return matches


def game_links(name):
    """Resolve configured download sources and official store pages together."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        source_future = pool.submit(source_links, name)
        store_future = pool.submit(store_links, name)
        return {'sources': source_future.result(), 'stores': store_future.result()}


def _json(url, data=None, headers=None):
    body = None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())
    request = Request(url, data=body, headers={'User-Agent': 'Yoink/0.4', **(headers or {})})
    if body and not isinstance(data, bytes):
        request.add_header('Content-Type', 'application/json')
    elif body:
        request.add_header('Content-Type', 'text/plain')
    with urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode())


def _game(item, source='steam'):
    cover = item.get('cover') or item.get('header_image') or item.get('capsule_image') or {}
    if isinstance(cover, dict):
        cover = cover.get('url', '')
    cover = _https_url(cover)
    if source == 'igdb' and cover and '/t_' not in cover:
        cover = cover.replace('/igdb/image/upload/', '/igdb/image/upload/t_cover_big/')
    timestamp = item.get('first_release_date') or 0
    release = time.strftime('%Y', time.gmtime(timestamp)) if timestamp else ''
    genres = [g.get('name', '') if isinstance(g, dict) else str(g) for g in item.get('genres', [])]
    platforms = [p.get('name', '') if isinstance(p, dict) else str(p) for p in item.get('platforms', [])]
    identity = str(item.get('id') or item.get('appid') or '')
    steam_appid = str(item.get('steam_appid') or item.get('appid') or (item.get('id') if source == 'steam' and str(item.get('id', '')).isdigit() else '') or '')
    grid_cover = cover
    detail_cover = cover
    grid_fallbacks = []
    detail_fallbacks = []
    if steam_appid.isdigit():
        # The catalogue and detail page use horizontal Steam header artwork.
        # Keep the old portrait URL in ``cover`` for callers that still expect
        # it, but never use that field for the discovery grid.
        steam_cover = 'https://cdn.cloudflare.steamstatic.com/steam/apps/' + steam_appid + '/library_600x900_2x.jpg'
        header = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/' + steam_appid + '/header.jpg'
        header_alt = 'https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/' + steam_appid + '/header.jpg'
        capsule = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/' + steam_appid + '/capsule_231x87.jpg'
        capsule_alt = 'https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/' + steam_appid + '/capsule_231x87.jpg'
        cover = steam_cover
        grid_cover = header
        detail_cover = _https_url(item.get('header_image') or item.get('capsule_image') or header)
        grid_fallbacks = [header_alt, capsule, capsule_alt]
        detail_fallbacks = [header, header_alt, capsule, capsule_alt]
    backup_cover = ('https://cdn.cloudflare.steamstatic.com/steam/apps/' + steam_appid + '/library_600x900.jpg') if steam_appid.isdigit() else ''
    return {'id': identity, 'name': item.get('name', 'Untitled'),
            'summary': item.get('summary') or item.get('short_description') or '',
            'cover': cover, 'release': release, 'rating': round(float(item.get('rating') or 0)),
            'genres': [x for x in genres if x], 'platforms': [x for x in platforms if x], 'source': source,
            'steamAppId': steam_appid, 'backupCover': backup_cover,
            'gridCover': grid_cover, 'gridFallbacks': grid_fallbacks,
            'detailCover': detail_cover, 'detailFallbacks': detail_fallbacks}


def _https_url(value):
    value = str(value or '')
    if value.startswith('//'):
        return 'https:' + value
    if value.startswith('http://'):
        return 'https://' + value[7:]
    return value


def _igdb_headers():
    data = settings.load()
    client, secret = data.get('igdb_client_id', '').strip(), data.get('igdb_client_secret', '').strip()
    if not client or not secret:
        return None
    token = _json('https://id.twitch.tv/oauth2/token', {'client_id': client, 'client_secret': secret, 'grant_type': 'client_credentials'})
    return {'Client-ID': client, 'Authorization': 'Bearer ' + token['access_token']}


def _igdb(query):
    headers = _igdb_headers()
    if not headers:
        return []
    items = _json('https://api.igdb.com/v4/games', query.encode(), headers)
    return [_game(item, 'igdb') for item in items]


def _steam_search(query):
    data = _json('https://store.steampowered.com/api/storesearch/?l=en&cc=us&term=' + quote(query))
    return _with_grid_covers([_game(item) for item in data.get('items', [])[:PAGE_SIZE]])


def _steam_trending(page=1):
    """Steam's public ranked search feed; no Steam Web API key required."""
    requested_start = max(0, (int(page) - 1) * PAGE_SIZE)
    markup = ''
    try:
        data = _json('https://store.steampowered.com/search/results/?query=&start=0&count=200&dynamic_data=&sort_by=_ASC&filter=globaltopsellers&infinite=1&cc=us&l=en')
        markup = data.get('results_html', '')
    except Exception:
        # Steam sometimes blocks the JSON search endpoint while its normal
        # public HTML search page remains available.
        try:
            request = Request('https://store.steampowered.com/search/?query=&start=0&count=200&filter=globaltopsellers', headers={'User-Agent': 'Yoink/0.4'})
            with urlopen(request, timeout=12) as response:
                markup = response.read().decode('utf-8', 'ignore')
        except Exception:
            markup = ''
    if markup:
        results = []
        for match in re.finditer(r'data-ds-appid="([0-9,]+)"[\s\S]*?<span class="title">\s*([^<]+)', markup):
            appid = match.group(1).split(',')[0]
            results.append(_game({'appid': appid, 'name': html.unescape(match.group(2).strip())}))
        if results:
            return _with_grid_covers(results[requested_start:requested_start + PAGE_SIZE])
    data = _json('https://store.steampowered.com/api/featuredcategories/?cc=us&l=en')
    items = data.get('specials', {}).get('items', []) + data.get('top_sellers', {}).get('items', [])
    seen, results = set(), []
    for item in items:
        game = _game(item)
        if game['id'] not in seen:
            seen.add(game['id']); results.append(game)
    return _with_grid_covers(results[requested_start:requested_start + PAGE_SIZE])


def _sgdb_headers():
    key = settings.load().get('steamgriddb_api_key', '').strip()
    return {'Authorization': 'Bearer ' + key} if key else None


def _sgdb_data(value):
    return value.get('data', []) if isinstance(value, dict) else value


def _sgdb_game(item):
    return _game({'id': item.get('id'), 'name': item.get('name'),
                  'appid': item.get('steam_appid')}, 'steamgriddb')


def _sgdb_covers(game_id):
    headers = _sgdb_headers()
    if not headers:
        return ''
    try:
        grids = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/grids/game/' + str(game_id) + '?dimensions=600x900', headers=headers))
    except Exception:
        grids = []
    if not grids:
        try:
            grids = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/grids/game/' + str(game_id), headers=headers))
        except Exception:
            grids = []
    portraits = [g for g in grids if (g.get('width', 0) and g.get('height', 0) and g['height'] >= g['width'])]
    chosen = portraits[0] if portraits else (grids[0] if grids else {})
    return chosen.get('url') or chosen.get('thumb', '')


def _sgdb_results(query=None, page=1):
    headers = _sgdb_headers()
    if not headers:
        return []
    if query:
        matches = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/search/autocomplete/' + quote(query), headers=headers))
    else:
        matches = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/games/hot?page=' + str(max(1, int(page))), headers=headers))
    results = []
    for item in matches[:PAGE_SIZE]:
        game = _sgdb_game(item)
        # Steam's library capsule is a consistent 600x900 portrait image.
        # Keep the SteamGridDB grid available as a fallback for games without
        # a Steam app ID or when the CDN asset is unavailable in the view.
        game['steamgridCover'] = _sgdb_covers(item.get('id'))
        if not game['cover'] or not game.get('steamAppId'):
            game['cover'] = game['steamgridCover']
        game['coverSource'] = 'Steam CDN'
        results.append(game)
    return results


def _with_grid_covers(results):
    """Resolve cover URLs without downloading image files."""
    return _cache_steam_covers(results)


def _cache_steam_covers(results):
    """Use the same Steam artwork source for catalogue and detail views.

    Steam's search feed gives us IDs, but not the final artwork URL.  The
    detail view uses ``appdetails.header_image``; fetch those details for the
    catalogue as well.  Requests are bounded to three workers and cached for
    the life of the backend process so page changes do not create an eight-way
    burst of duplicate lookups.
    """
    appids = []
    for game in results:
        appid = str(game.get('steamAppId') or '')
        if appid.isdigit() and appid not in appids:
            appids.append(appid)

    now = time.time()
    details = {}
    missing = []
    for appid in appids:
        cached = _STEAM_DETAILS_CACHE.get(appid)
        if cached:
            stamp, data, success = cached
            ttl = _STEAM_DETAILS_SUCCESS_TTL if success else _STEAM_DETAILS_CACHE_TTL
        else:
            stamp, data, success, ttl = 0, {}, False, 0
        if cached and now - stamp < ttl:
            details[appid] = data
        else:
            missing.append(appid)
    if missing:
        with ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(_steam_detail, missing))
        details.update(dict(zip(missing, fetched)))

    def unique(values):
        return list(dict.fromkeys(value for value in values if value))

    for game in results:
        appid = str(game.get('steamAppId') or '')
        data = details.get(appid, {})
        if not appid.isdigit():
            game.setdefault('gridCover', game.get('cover', ''))
            game.setdefault('gridFallbacks', [])
            game.setdefault('detailCover', game.get('cover', ''))
            game.setdefault('detailFallbacks', [])
            continue
        header = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/' + appid + '/header.jpg'
        header_alt = 'https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/' + appid + '/header.jpg'
        capsule = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/' + appid + '/capsule_231x87.jpg'
        capsule_alt = 'https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/' + appid + '/capsule_231x87.jpg'
        steam_cover = _https_url(data.get('header_image') or data.get('capsule_image') or '')
        grid_cover = steam_cover or game.get('gridCover') or header
        game['gridCover'] = grid_cover
        game['gridFallbacks'] = unique([header, header_alt, capsule, capsule_alt] + list(game.get('gridFallbacks') or []))
        game['detailCover'] = steam_cover or game.get('detailCover') or grid_cover
        game['detailFallbacks'] = unique([header, header_alt, capsule, capsule_alt] + list(game.get('detailFallbacks') or []))
    return results


def trending(page=1):
    page = max(1, min(5, int(page)))
    # Steam's public ranked feed is the most reliable no-key trending source.
    try:
        return _steam_trending(page)
    except Exception:
        pass
    try:
        offset = max(0, (int(page) - 1) * PAGE_SIZE)
        return _with_grid_covers(_igdb('fields name,summary,cover.url,first_release_date,rating,genres.name,platforms.name; sort popularity desc; limit ' + str(PAGE_SIZE) + '; offset ' + str(offset) + ';')) or _steam_trending(page)
    except Exception:
        return _steam_trending()


def search(query):
    query = str(query).strip()
    if not query or len(query) > 200:
        raise ValueError('Enter a game title (up to 200 characters).')
    try:
        return _with_grid_covers(_igdb('search "' + query.replace('"', '') + '"; fields name,summary,cover.url,first_release_date,rating,genres.name,platforms.name; limit 20;')) or _steam_search(query)
    except Exception:
        return _steam_search(query)


def detail(identity, source='steam'):
    if not identity or not str(identity).isdigit():
        raise ValueError('Invalid game selection.')
    if source == 'steamgriddb':
        headers = _sgdb_headers()
        if headers:
            item = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/games/id/' + str(int(identity)), headers=headers))
            game = _sgdb_game(item)
            game['cover'] = _sgdb_covers(identity)
            game['coverSource'] = 'SteamGridDB'
            return game
    if source == 'igdb':
        results = _igdb('where id = ' + str(int(identity)) + '; fields name,summary,cover.url,first_release_date,rating,genres.name,platforms.name;')
        if results:
            return results[0]
    item = _steam_detail(str(int(identity)))
    return _with_grid_covers([_game({'appid': identity, **item}, 'steam')])[0]
