"""Private Yoinker settings; credentials never travel in command arguments."""
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

FIELDS = {
    'game_always_checked_urls',
    'spotify_client_id', 'qobuz_email', 'qobuz_password', 'qobuz_user_id',
    'qobuz_token', 'qobuz_auth_mode', 'qobuz_app_id', 'qobuz_app_secret', 'deezer_arl', 'tidal_user_id', 'tidal_country_code',
    'tidal_access_token', 'tidal_refresh_token', 'tidal_token_expiry',
    'youtube_cookies',
}
SECRET_FIELDS = {'qobuz_app_secret', 'qobuz_password', 'qobuz_token', 'deezer_arl', 'tidal_access_token', 'tidal_refresh_token'}


def qobuz_auth_mode(data):
    # Preserve the former token-login preference until the user selects a mode.
    return data.get('qobuz_auth_mode') or ('token' if data.get('qobuz_user_id') and data.get('qobuz_token') else 'password')


def directory():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'yoinker'


def load():
    path = directory() / 'settings.json'
    return json.loads(path.read_text()) if path.exists() else {}


def update(values):
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    lock = os.open(folder / '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load()
        data.update(values)
        fd, name = tempfile.mkstemp(dir=folder, prefix='.settings-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, folder / 'settings.json')
        finally:
            if os.path.exists(name):
                os.unlink(name)
    finally:
        os.close(lock)
    return data


def save_form(values):
    clean = {}
    for key, value in values.items():
        if key not in FIELDS or not isinstance(value, str):
            raise ValueError('Invalid configuration field.')
        # Blank secret fields preserve the saved value; forgetting is explicit.
        if key in SECRET_FIELDS and not value:
            continue
        clean[key] = hashlib.md5(value.encode()).hexdigest() if key == 'qobuz_password' else value.strip()
    if 'qobuz_auth_mode' in clean and clean['qobuz_auth_mode'] not in ('password', 'token'):
        raise ValueError('Choose a valid Qobuz login method.')
    if clean.get('tidal_token_expiry'):
        try:
            float(clean['tidal_token_expiry'])
        except ValueError:
            raise ValueError('Tidal token expiry must be a Unix timestamp.') from None
    old = load()
    if 'spotify_client_id' in clean and clean['spotify_client_id'] != old.get('spotify_client_id'):
        clean['spotify_token'] = {}
    update(clean)


def public_settings():
    data = load()
    return {key: (bool(data.get(key)) if key in SECRET_FIELDS else data.get(key, '')) for key in FIELDS} | {
        'qobuz_auth_mode': qobuz_auth_mode(data),
        'spotify_connected': bool(data.get('spotify_token', {}).get('refresh_token')),
    }
