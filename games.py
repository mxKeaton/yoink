"""Small, read-only game catalogue client.

IGDB is used when credentials are configured. Steam's public store endpoints
provide a useful fallback, so browsing works without an account or API key.
Download controls intentionally remain placeholders.
"""
import json
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, quote_plus, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import settings

PAGE_SIZE = 18

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
    """Return configured sites whose simple title slug responds successfully."""
    slug = re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')
    if not slug:
        return []
    def check(base):
        encoded_title = quote_plus(str(name).lower())
        if 'ankergames.net' in base.lower():
            # Ankergames uses /game/<slug> and currently returns 403 to
            # non-browser clients even for real pages.
            candidates = (urljoin(base + '/game/', slug), urljoin(base + '/games/', slug))
        else:
            candidates = (urljoin(base + '/', slug), urljoin(base + '/', encoded_title),
                          urljoin(base + '/game/', slug), urljoin(base + '/games/', slug))
        match_url = candidates[0]
        valid = False
        for url in candidates:
            try:
                request = Request(url, headers={'User-Agent': 'Yoinker/0.4'})
                with urlopen(request, timeout=4) as response:
                    final_url = response.geturl() or url
                    body = response.read(65536).decode('utf-8', 'ignore').lower()
                    final_path = urlparse(final_url).path.rstrip('/').lower()
                    error_url = (final_path in ('', '/') or any(token in final_path for token in ('/error', '/404', 'not-found', 'page-not-found')))
                    error_body = any(token in body for token in ('page not found', '404 not found', 'error occurred', 'does not exist'))
                    if 200 <= response.status < 400 and not error_url and not error_body:
                        match_url, valid = final_url, True
                        break
            except HTTPError as error:
                if error.code == 403 and 'ankergames.net' in base.lower():
                    return {'base': base, 'url': url, 'valid': True}
            except Exception:
                continue
        return {'base': base, 'url': match_url, 'valid': valid}
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, source_urls()))
    # Do not expose guessed error routes as clickable source buttons.  A
    # number of game sites return a branded 404 page with HTTP 200, so the
    # per-page checks above are required before a route is considered usable.
    return [result for result in results if result['valid']]


def _json(url, data=None, headers=None):
    body = None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())
    request = Request(url, data=body, headers={'User-Agent': 'Yoinker/0.4', **(headers or {})})
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
    if cover.startswith('//'):
        cover = 'https:' + cover
    if cover.startswith('http://'):
        cover = 'https://' + cover[7:]
    if source == 'igdb' and cover and '/t_' not in cover:
        cover = cover.replace('/igdb/image/upload/', '/igdb/image/upload/t_cover_big/')
    timestamp = item.get('first_release_date') or 0
    release = time.strftime('%Y', time.gmtime(timestamp)) if timestamp else ''
    genres = [g.get('name', '') if isinstance(g, dict) else str(g) for g in item.get('genres', [])]
    platforms = [p.get('name', '') if isinstance(p, dict) else str(p) for p in item.get('platforms', [])]
    identity = str(item.get('id') or item.get('appid') or '')
    steam_appid = str(item.get('steam_appid') or item.get('appid') or (item.get('id') if source == 'steam' and str(item.get('id', '')).isdigit() else '') or '')
    if steam_appid.isdigit():
        steam_cover = 'https://cdn.cloudflare.steamstatic.com/steam/apps/' + steam_appid + '/library_600x900_2x.jpg'
        cover = steam_cover
    backup_cover = ('https://cdn.cloudflare.steamstatic.com/steam/apps/' + steam_appid + '/library_600x900.jpg') if steam_appid.isdigit() else ''
    return {'id': identity, 'name': item.get('name', 'Untitled'),
            'summary': item.get('summary') or item.get('short_description') or 'No description available.',
            'cover': cover, 'release': release, 'rating': round(float(item.get('rating') or 0)),
            'genres': [x for x in genres if x], 'platforms': [x for x in platforms if x], 'source': source,
            'steamAppId': steam_appid, 'backupCover': backup_cover}


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
    try:
        data = _json('https://store.steampowered.com/search/results/?query=&start=0&count=200&dynamic_data=&sort_by=_ASC&filter=globaltopsellers&infinite=1&cc=us&l=en')
        markup = data.get('results_html', '')
        results = []
        for match in re.finditer(r'data-ds-appid="([0-9,]+)"[\s\S]*?<span class="title">\s*([^<]+)', markup):
            appid = match.group(1).split(',')[0]
            results.append(_game({'appid': appid, 'name': html.unescape(match.group(2).strip())}))
        if results:
            return _with_grid_covers(results[requested_start:requested_start + PAGE_SIZE])
    except Exception:
        pass
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
    return _game({'id': item.get('id'), 'name': item.get('name'), 'summary': item.get('genres', []) and 'SteamGridDB game',
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
    """Resolve Steam artwork URLs and serve them directly to QML."""
    appids = [g.get('steamAppId') for g in results if g.get('steamAppId')]
    details = {}
    def get_detail(appid):
        try:
            payload = _json('https://store.steampowered.com/api/appdetails?appids=' + appid + '&l=en')
            return appid, payload.get(appid, {}).get('data', {})
        except Exception:
            return appid, {}
    if appids:
        with ThreadPoolExecutor(max_workers=8) as pool:
            details = dict(pool.map(get_detail, appids))
    pending = []
    for game in results:
        appid = game.get('steamAppId', '')
        data = details.get(appid, {})
        portrait_url = data.get('library_capsule_2x') or data.get('library_capsule')
        detail_url = data.get('header_image') or data.get('capsule_image')
        sgdb_key = settings.load().get('steamgriddb_api_key', '').strip()
        if not portrait_url and sgdb_key and appid:
            pending.append((game, appid, detail_url, sgdb_key))
        if portrait_url:
            pending.append((game, appid, detail_url, portrait_url))
        else:
            game['cover'] = detail_url or ''; game['backupCover'] = detail_url or game.get('backupCover', ''); game['portraitCover'] = ''
    def resolve(item):
        game, appid, detail, value = item
        portrait = value
        if value == sgdb_key:
            try:
                match = _sgdb_data(_json('https://www.steamgriddb.com/api/v2/games/steam/' + appid, headers={'Authorization': 'Bearer ' + value}))
                portrait = _sgdb_covers(match['id']) if isinstance(match, dict) and match.get('id') else ''
            except Exception:
                portrait = ''
        return game, detail, portrait
    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(resolve, pending))
    for game, detail_url, portrait_url in resolved:
        game['cover'] = detail_url or ''
        game['backupCover'] = detail_url or game.get('backupCover', '')
        if not portrait_url:
            game['portraitCover'] = ''
            continue
        game['portraitCover'] = portrait_url
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
    data = _json('https://store.steampowered.com/api/appdetails?appids=' + str(int(identity)) + '&l=en')
    item = data.get(str(int(identity)), {}).get('data', {})
    return _with_grid_covers([_game({'appid': identity, **item}, 'steam')])[0]
