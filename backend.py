#!/usr/bin/python
"""JSON-over-stdin bridge for the Yoinker popup."""
import asyncio
import json
import logging
import signal
import sys

# Omarchy watches every file under the plugin directory, including __pycache__.
# Cache writes trigger a shell reload that destroys this process and its popup.
# Set this before any local imports, including when run outside the QML launcher.
sys.dont_write_bytecode = True

import settings


def terminate(*_):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, terminate)


def snapshot():
    print('CONFIG:' + json.dumps(settings.public_settings()), flush=True)


async def connect_tidal():
    from streamrip.client import TidalClient
    from streamrip.config import Config
    from streamrip.rip.prompter import TidalPrompter
    config = Config.defaults()
    client = TidalClient(config)
    try:
        await TidalPrompter(config, client).prompt_and_login()
        c = config.session.tidal
        settings.update({'tidal_' + key: str(getattr(c, key)) for key in
                         ('user_id', 'country_code', 'access_token', 'refresh_token', 'token_expiry')})
        print('Tidal connected.', flush=True)
    finally:
        session = getattr(client, 'session', None)
        if session and not session.closed:
            await session.close()


def main(options):
    action = options.get('action', 'download')
    if action == 'config-load':
        snapshot()
    elif action == 'config-save':
        settings.save_form(options.get('values', {}))
        snapshot()
        print('Configuration saved.', flush=True)
    elif action == 'config-forget':
        platform = options.get('platform')
        if platform not in ('spotify', 'qobuz', 'deezer', 'tidal', 'youtube'):
            raise ValueError('Unknown platform.')
        clear = {key: '' for key in settings.FIELDS if key.startswith(platform + '_')}
        if platform == 'spotify':
            clear['spotify_token'] = {}
        settings.update(clear)
        snapshot()
        print('Platform configuration cleared.', flush=True)
    elif action == 'spotify-connect':
        settings.save_form(options.get('values', {}))
        import spotify
        spotify.connect()
        snapshot()
    elif action == 'tidal-connect':
        settings.save_form(options.get('values', {}))
        asyncio.run(connect_tidal())
        snapshot()
    elif action == 'search':
        import lookup
        results = lookup.search(options.get('query', ''))
        print('SEARCH:' + json.dumps(results), flush=True)
        print(f'{len(results)} songs found.' if results else 'No songs found. Try adding the artist name.', flush=True)
    elif action in ('download', 'formats'):
        url = options.get('url', '').strip()
        if options.get('selection') or url.startswith('spotify:') or 'open.spotify.com' in url:
            import music
            return asyncio.run(music.run(options))
        import download
        return download.gui_main(json.dumps(options))
    else:
        raise ValueError('Unknown operation.')
    return 0


if __name__ == '__main__':
    # Third-party debug/error logging may contain account tokens or signed URLs.
    logging.disable(logging.CRITICAL)
    try:
        options = json.loads(sys.stdin.readline())
        sys.exit(main(options))
    except (KeyboardInterrupt, EOFError):
        print('Cancelled.', flush=True)
        sys.exit(130)
    except (ValueError, RuntimeError) as error:
        # Our own validation/API messages contain no credentials.
        print(str(error), flush=True)
        sys.exit(1)
    except ImportError:
        print('Missing dependency. Install streamrip and python-ytmusicapi for Spotify downloads.', flush=True)
        sys.exit(1)
    except Exception as error:
        print(f'{type(error).__name__}: operation failed. Check platform configuration and connection.', flush=True)
        sys.exit(1)
