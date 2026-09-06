#!/usr/bin/env python3
"""Spotify PKCE and metadata, adapted from ECHO’s spotify-to-qobuz helper."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request


import settings
REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"


def request_json(url: str, *, headers=None, data=None, method=None):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = {401: "Reconnect Spotify in Configuration.", 403: "Spotify denied access. Check your app's allowed users and playlist access.", 429: "Spotify rate limit reached; try again later."}.get(exc.code, "Spotify request failed.")
        raise RuntimeError(f"Spotify HTTP {exc.code}: {detail}") from exc



def pkce_login(client_id: str) -> dict:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if urllib.parse.urlsplit(self.path).path != "/callback" or query.get("state", [""])[0] != state:
                status, message = 400, "Authorization failed: state mismatch."
            elif "error" in query:
                result["error"] = query["error"][0]
                status, message = 400, "Spotify authorization was denied."
            else:
                result["code"] = query.get("code", [""])[0]
                status, message = 200, "Spotify authorization complete. You may close this tab."
            body = message.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    })
    auth_url = "https://accounts.spotify.com/authorize?" + params
    class CallbackServer(http.server.HTTPServer):
        allow_reuse_address = True

    server = CallbackServer(("127.0.0.1", 8765), Callback)
    server.timeout = 1
    print("Opening Spotify authorization in your browser…", flush=True)
    print("OPEN:" + auth_url, flush=True)
    deadline = time.monotonic() + 300
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result.get("code"):
        raise RuntimeError(result.get("error", "Spotify authorization timed out"))

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()
    token = request_json(
        "https://accounts.spotify.com/api/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        method="POST",
    )
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600)) - 60
    return token


def spotify_token(config: dict, client_id: str) -> str:
    token = config.get("spotify_token", {})
    if token.get("access_token") and token.get("expires_at", 0) > time.time():
        return token["access_token"]
    if token.get("refresh_token"):
        data = urllib.parse.urlencode({
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        }).encode()
        refreshed = request_json(
            "https://accounts.spotify.com/api/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            method="POST",
        )
        refreshed.setdefault("refresh_token", token["refresh_token"])
        refreshed["expires_at"] = int(time.time()) + int(refreshed.get("expires_in", 3600)) - 60
        config["spotify_token"] = refreshed
        settings.update({"spotify_token": refreshed})
        return refreshed["access_token"]
    token = pkce_login(client_id)
    config["spotify_token"] = token
    settings.update({"spotify_token": token})
    return token["access_token"]


def spotify_source(value: str) -> tuple[str, str]:
    if value.startswith("spotify:"):
        match = re.fullmatch(r"spotify:(track|playlist|album|artist):([A-Za-z0-9]{22})", value)
    else:
        url = urllib.parse.urlsplit(value)
        if url.scheme != "https" or url.hostname != "open.spotify.com" or url.username or url.password:
            raise RuntimeError("Enter a Spotify track, playlist, album, or artist link.")
        match = re.fullmatch(r"/(?:intl-[a-z]+/)?(track|playlist|album|artist)/([A-Za-z0-9]{22})/?", url.path)
    if not match:
        raise RuntimeError("Expected a Spotify song, playlist, album, or artist link with a 22-character ID.")
    return match.group(1), match.group(2)


def spotify_tracks(pid: str, token: str) -> list[dict]:
    url = f"https://api.spotify.com/v1/playlists/{pid}/items?limit=50"
    headers = {"Authorization": f"Bearer {token}"}
    tracks = []
    while url:
        if not url.startswith("https://api.spotify.com/v1/"):
            raise RuntimeError("Invalid Spotify pagination URL.")
        page = request_json(url, headers=headers)
        for wrapper in page.get("items", []):
            track = wrapper.get("item") or wrapper.get("track")
            if track and not track.get("is_local") and track.get("name") and track.get("type", "track") == "track":
                tracks.append(track)
        url = page.get("next")
    if not tracks:
        raise RuntimeError("Spotify returned no playlist items; the playlist must be owned by or shared with this app user")
    return tracks


def spotify_playlist_name(pid: str, token: str) -> str:
    playlist = request_json(
        f"https://api.spotify.com/v1/playlists/{pid}?fields=name",
        headers={"Authorization": f"Bearer {token}"},
    )
    name = str(playlist.get("name", "")).strip()
    if not name:
        raise RuntimeError("Spotify returned a playlist without a name")
    return name


def spotify_track(tid: str, token: str) -> dict:
    track = request_json(
        f"https://api.spotify.com/v1/tracks/{tid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not track.get("name"):
        raise RuntimeError("Spotify returned a track without a name")
    return track



def paginated_items(url, token, first=None):
    seen = set()
    while url:
        if not url.startswith("https://api.spotify.com/v1/") or url in seen:
            raise RuntimeError("Invalid Spotify pagination URL.")
        seen.add(url)
        page = first if first is not None else request_json(url, headers={"Authorization": f"Bearer {token}"})
        first = None
        yield from page.get("items", [])
        url = page.get("next")


def spotify_album(identity, token):
    album = request_json(f"https://api.spotify.com/v1/albums/{identity}", headers={"Authorization": f"Bearer {token}"})
    url = f"https://api.spotify.com/v1/albums/{identity}/tracks?limit=50"
    tracks = [item for item in paginated_items(url, token, album.get("tracks"))
              if item and item.get("name") and item.get("id") and not item.get("is_local")]
    if not tracks:
        raise RuntimeError("Spotify returned no available album tracks.")
    return album.get("name", "Album"), tracks


def spotify_artist(identity, token):
    artist = request_json(f"https://api.spotify.com/v1/artists/{identity}", headers={"Authorization": f"Bearer {token}"})
    url = f"https://api.spotify.com/v1/artists/{identity}/albums?include_groups=album,single&limit=50"
    albums = list(paginated_items(url, token))
    tracks, seen_albums, seen_tracks = [], set(), set()
    for index, album in enumerate(albums, 1):
        album_id = album.get("id")
        if not album_id or album_id in seen_albums:
            continue
        seen_albums.add(album_id)
        print(f'Reading artist release {index}/{len(albums)}: {album.get("name", "Album")}', flush=True)
        _, items = spotify_album(album_id, token)
        for item in items:
            if item["id"] not in seen_tracks:
                tracks.append(item)
                seen_tracks.add(item["id"])
    if not tracks:
        raise RuntimeError("Spotify returned no album/single tracks for this artist.")
    return artist.get("name", "Artist"), tracks


def tracks_from_link(value):
    kind, identity = spotify_source(value)
    config = settings.load()
    client_id = config.get("spotify_client_id", "")
    if not client_id:
        raise RuntimeError("Enter your Spotify client ID and connect in Configuration first.")
    if not config.get("spotify_token"):
        raise RuntimeError("Connect Spotify in Configuration first.")
    token = spotify_token(config, client_id)
    if kind == "track":
        track = spotify_track(identity, token)
        return track["name"], [track]
    if kind == "album":
        return spotify_album(identity, token)
    if kind == "artist":
        return spotify_artist(identity, token)
    return spotify_playlist_name(identity, token), spotify_tracks(identity, token)


def connect():
    client_id = settings.load().get("spotify_client_id", "")
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", client_id):
        raise RuntimeError("Save a valid Spotify client ID first.")
    token = pkce_login(client_id)
    settings.update({"spotify_token": token})
    print("Spotify connected.", flush=True)
