"""Rive movie catalogue and source lookup."""
import base64
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BACKEND_URL = "https://backend.rivestream.app/api/backendfetch"
PROVIDERS_URL = "https://scrapper.rivestream.app/api/providers"
PROVIDER_URL = "https://scrapper.rivestream.app/api/provider"
WATCH_URL = "https://www.rivestream.app/watch"
IMAGE_BASE = "https://image.tmdb.org/t/p/"
MOVIE_SITE_ROUTES = (
    ("Rive", lambda movie_id: WATCH_URL + "?" + urlencode({"type": "movie", "id": str(movie_id)})),
    ("7Movies", lambda movie_id: "https://7movies.in/?" + urlencode({"open": "movie-" + str(movie_id), "watch": "1"})),
    ("Movy", lambda movie_id: "https://www.movy.sx/movie/" + str(movie_id) + "/watch"),
    ("bCine", lambda movie_id: "https://bcine.ru/movie/" + str(movie_id)),
)
DEFAULT_PROVIDERS = (
    "apex", "pulse", "solstice", "quasar", "horizon", "primevids",
    "flowcast", "asiacloud", "citadel", "hindicast", "guru",
)

# Rive's browser client uses these public lookup tokens to sign its backend
# requests. They are not user credentials; the catalogue is unavailable
# without the same public request shape used by the site.
_PUBLIC_KEYS = (
    "4Z7lUo", "gwIVSMD", "PLmz2elE2v", "Z4OFV0", "SZ6RZq6Zc",
    "zhJEFYxrz8", "FOm7b0", "axHS3q4KDq", "o9zuXQ", "4Aebt",
    "wgjjWwKKx", "rY4VIxqSN", "kfjbnSo", "2DyrFA1M", "YUixDM9B",
    "JQvgEj0", "mcuFx6JIek", "eoTKe26gL", "qaI9EVO1rB", "0xl33btZL",
    "1fszuAU", "a7jnHzst6P", "wQuJkX", "cBNhTJlEOf", "KNcFWhDvgT",
    "XipDGjST", "PCZJlbHoyt", "2AYnMZkqd", "HIpJh", "KH0C3iztrG",
    "W81hjts92", "rJhAT", "NON7LKoMQ", "NMdY3nsKzI", "t4En5v",
    "Qq5cOQ9H", "Y9nwrp", "VX5FYVfsf", "cE5SJG", "x1vj1", "HegbLe",
    "zJ3nmt4OA", "gt7rxW57dq", "clIE9b", "jyJ9g", "B5jXjMCSx",
    "cOzZBZTV", "FTXGy", "Dfh1q1", "ny9jqZ2POI", "X2NnMn", "MBtoyD",
    "qz4Ilys7wB", "68lbOMye", "3YUJnmxp", "1fv5Imona", "PlfvvXD7mA",
    "ZarKfHCaPR", "owORnX", "dQP1YU", "dVdkx", "qgiK0E", "cx9wQ",
    "5F9bGa", "7UjkKrp", "Yvhrj", "wYXez5Dg3", "pG4GMU",
    "MwMAu", "rFRD5wlM",
)


def _u32(value):
    return value & 0xFFFFFFFF


def _s32(value):
    value = _u32(value)
    return value if value < 0x80000000 else value - 0x100000000


def _shl(value, amount):
    return _s32(_u32(value) << (amount & 31))


def _shr(value, amount):
    return _u32(value) >> (amount & 31)


def _js_hex(value):
    text = ("-" + format(-value, "x")) if value < 0 else format(value, "x")
    return text.rjust(8, "0")


def _rive_hash(value):
    """Mirror the small hash used by Rive's public web client."""
    text = str(value)
    state = _s32(3735928559 ^ len(text))
    for index, character in enumerate(text):
        code = ord(character)
        code = _s32(code ^ (_s32(131 * index + 89) ^ _shl(code, index % 5))) & 255
        state = _s32(_u32(_shl(state, 7) | _shr(state, 25)) ^ code)
        state = _u32((_u32(state) & 0xFFFF) * 60205 + _shr(state, 16) * 60205 * 65536)
        state = _s32(_u32(state) ^ _shr(state, 11))

    state = _s32(_u32(state) ^ _shr(state, 15))
    state = _u32((state & 0xFFFF) * 49842 + (((state >> 16) * 49842) & 0xFFFF) * 65536)
    state = _s32(_u32(state) ^ _shr(state, 13))
    state = _u32((state & 0xFFFF) * 40503 + (((state >> 16) * 40503) & 0xFFFF) * 65536)
    state = _s32(_u32(state) ^ _shr(state, 16))
    state = _u32((state & 0xFFFF) * 10196 + (((state >> 16) * 10196) & 0xFFFF) * 65536)
    state = _s32(_u32(state) ^ _shr(state, 15))
    return _js_hex(state)


def _rive_input_hash(value):
    text = str(value)
    state = 0
    for index, character in enumerate(text):
        code = ord(character)
        state = _u32(code + _shl(state, 6) + _shl(state, 16) - state)
        right_shift = (32 - index % 5) % 32
        rotated = _u32(_shl(state, index % 5) | _shr(state, right_shift))
        state = _s32(_u32(state) ^ _u32(rotated ^ (_shl(code, index % 7) | _shr(code, 8 - index % 7))))
        state = _u32(state + _s32(_shr(state, 11) ^ _shl(state, 3)))
    state = _s32(_u32(state) ^ _shr(state, 15))
    state = _u32((state & 0xFFFF) * 49842 + (((state >> 16) * 49842) & 0xFFFF) * 65536)
    state = _s32(_u32(state) ^ _shr(state, 13))
    state = _u32((state & 0xFFFF) * 40503 + (((state >> 16) * 40503) & 0xFFFF) * 65536)
    state = _s32(_u32(state) ^ _shr(state, 16))
    return _js_hex(state)


def _secret(value=None):
    if value is None:
        return "rive"
    text = str(value)
    try:
        numeric = int(text)
        checksum = numeric
    except (TypeError, ValueError):
        checksum = sum(ord(character) for character in text)
    token = _PUBLIC_KEYS[checksum % len(_PUBLIC_KEYS)]
    split = (checksum % len(text)) // 2
    inserted = text[:split] + token + text[split:]
    return base64.b64encode(_rive_hash(_rive_input_hash(inserted)).encode()).decode()


def _json(url, timeout=12):
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Yoink/0.6",
    })
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("success") is False:
        raise RuntimeError(payload.get("message") or "Rive returned an error.")
    return payload


def _backend(request_id, page=1, query=None, movie_id=None):
    values = {
        "requestID": request_id,
        "language": "en-US",
        "page": max(1, int(page or 1)),
        "secretKey": _secret(movie_id if movie_id is not None else query),
        "proxyMode": "undefined",
    }
    if query is not None:
        values["query"] = query
    if movie_id is not None:
        values["id"] = movie_id
    payload = _json(BACKEND_URL + "?" + urlencode(values), timeout=20)
    if not isinstance(payload, dict):
        raise RuntimeError("Rive returned an invalid response.")
    return payload


def _image(path, size):
    return IMAGE_BASE + size + path if path else ""


def _movie(item):
    title = item.get("title") or item.get("name") or "Untitled movie"
    release_date = item.get("release_date") or ""
    return {
        "id": str(item.get("id", "")),
        "name": title,
        "year": release_date[:4],
        "summary": item.get("overview") or "",
        "rating": item.get("vote_average") or 0,
        "gridCover": _image(item.get("poster_path"), "w342"),
        "gridFallbacks": [_image(item.get("poster_path"), "w500")],
        "source": "rive",
    }


def _results(payload):
    return [_movie(item) for item in payload.get("results", []) if item.get("id")]


def trending(page=1):
    return _results(_backend("trendingMovie", page=page))


def search(query, page=1):
    query = str(query or "").strip()
    if not query:
        raise ValueError("Enter a movie title to search.")
    return _results(_backend("searchMovie", page=page, query=query))


def detail(movie_id):
    if movie_id in (None, ""):
        raise ValueError("A movie ID is required.")
    payload = _backend("movieData", movie_id=movie_id)
    result = _movie(payload)
    result["genres"] = [genre.get("name") for genre in payload.get("genres", []) if genre.get("name")]
    result["runtime"] = payload.get("runtime") or 0
    result["tagline"] = payload.get("tagline") or ""
    result["homepage"] = payload.get("homepage") or ""
    return result


def _provider_names():
    try:
        payload = _json(PROVIDERS_URL, timeout=6)
        providers = payload.get("data", []) if isinstance(payload, dict) else []
        providers = [str(provider).strip() for provider in providers if str(provider).strip()]
        return providers or list(DEFAULT_PROVIDERS)
    except Exception:
        return list(DEFAULT_PROVIDERS)


def _provider_sources(provider, movie_id):
    try:
        payload = _json(PROVIDER_URL + "?" + urlencode({"provider": provider, "id": movie_id}), timeout=7)
    except Exception:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    sources = data.get("sources", [])
    if isinstance(sources, dict):
        sources = [sources]
    return [
        {
            "provider": item.get("source") or item.get("provider") or provider,
            "url": item.get("url"),
        }
        for item in sources
        if isinstance(item, dict) and str(item.get("url", "")).startswith(("http://", "https://"))
    ]


def _page_available(url):
    try:
        request = Request(url, headers={"Accept": "text/html", "User-Agent": "Yoink/0.6"})
        with urlopen(request, timeout=8) as response:
            final_url = response.geturl() or url
            body = response.read(65536).decode("utf-8", "ignore").lower()
            parsed_url = urlparse(final_url)
            final_path = parsed_url.path.rstrip("/").lower()
            error_url = (final_path in ("", "/") and not parsed_url.query) or any(token in final_path for token in ("/error", "/404", "not-found", "page-not-found"))
            error_body = any(token in body for token in (
                "page not found", "404 not found", "error occurred", "does not exist",
                "just a moment", "enable javascript and cookies", "cf-chl-",
            ))
            return 200 <= response.status < 400 and not error_url and not error_body
    except (HTTPError, URLError, socket.timeout, TimeoutError, OSError):
        return False
    except Exception:
        return False


def source_links(movie_id):
    if movie_id in (None, ""):
        raise ValueError("A movie ID is required.")
    found = []
    providers = _provider_names()
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(_provider_sources, provider, movie_id): provider for provider in providers}
        responses = {}
        for job in as_completed(jobs):
            responses[jobs[job]] = job.result()
    for provider in providers:
        found.extend(responses.get(provider, []))

    candidates = [{"label": label, "watchUrl": route(movie_id)} for label, route in MOVIE_SITE_ROUTES]
    with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        checks = list(pool.map(lambda item: _page_available(item["watchUrl"]), candidates))

    unique = []
    seen = set()
    for item, available in zip(candidates, checks):
        if not available or item["watchUrl"] in seen:
            continue
        seen.add(item["watchUrl"])
        unique.append(item)
    return unique
