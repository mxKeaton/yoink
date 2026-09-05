"""Account-free title lookup using the YouTube Music song catalog."""
import re


def search(query):
    from ytmusicapi import YTMusic
    query = str(query).strip()
    if not query or len(query) > 300:
        raise ValueError('Enter a title or artist and title (up to 300 characters).')
    results = []
    seen = set()
    for item in YTMusic().search(query, filter='songs', limit=20):
        identity = item.get('videoId', '')
        if item.get('resultType') != 'song' or not re.fullmatch(r'[A-Za-z0-9_-]{11}', identity) or identity in seen:
            continue
        artists = [a.get('name', '') for a in item.get('artists', []) if a.get('name')]
        if not item.get('title') or not artists:
            continue
        seen.add(identity)
        results.append({'videoId': identity, 'title': item['title'], 'artists': artists,
                        'album': (item.get('album') or {}).get('name', ''),
                        'duration': item.get('duration_seconds') or 0,
                        'durationLabel': item.get('duration') or ''})
        if len(results) == 20:
            break
    return results


def selected_track(value):
    if not isinstance(value, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(value.get('videoId', ''))):
        raise ValueError('Select a song from search results first.')
    title = value.get('title')
    artists = value.get('artists')
    if not isinstance(title, str) or not title.strip() or not isinstance(artists, list) or not artists or not all(isinstance(a, str) and a for a in artists):
        raise ValueError('The selected song has incomplete metadata. Search again.')
    duration = float(value.get('duration') or 0)
    if not 0 <= duration <= 86400:
        raise ValueError('Invalid song duration.')
    return {'id': 'youtube:' + value['videoId'], 'name': title,
            'artists': [{'name': name} for name in artists], 'duration_ms': duration * 1000,
            'external_ids': {}, 'youtube_id': value['videoId']}
