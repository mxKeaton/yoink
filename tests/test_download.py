import unittest
from pathlib import Path
from download import command, youtube_url


class DownloadTests(unittest.TestCase):
    def test_source_boundary(self):
        for url in ('https://youtu.be/abc', 'https://www.youtube.com/watch?v=abc&list=xyz', 'https://music.youtube.com/watch?v=abc'):
            self.assertEqual(youtube_url(url), url)
        for url in ('file:///tmp/a', 'https://youtube.com.evil.test/a', 'https://youtube.com@evil.test/a', '--exec=touch /tmp/a'):
            with self.assertRaises(ValueError):
                youtube_url(url)

    def test_audio_and_literal_arguments(self):
        url = 'https://youtu.be/abc?x=$(touch /tmp/unwanted)'
        args = command(url, 'Audio', Path('/tmp/music with spaces'), 'mp3', '192K')
        self.assertEqual(args[-2:], ['--', url])
        self.assertIn('--no-playlist', args)
        self.assertIn('--ignore-config', args)
        self.assertIn('--extract-audio', args)
        self.assertEqual(args[args.index('--audio-quality') + 1], '192K')
        self.assertEqual(args[args.index('--paths') + 1], '/tmp/music with spaces')

    def test_video_height_and_container(self):
        args = command('https://youtu.be/abc', 'Video', Path('/tmp'), 'mkv', '1080', True, True)
        self.assertEqual(args[args.index('-f') + 1], 'bv*[height<=1080]+ba/b[height<=1080]')
        self.assertIn('--remux-video', args)
        self.assertIn('--embed-subs', args)
        self.assertNotIn('--extract-audio', args)


if __name__ == '__main__':
    unittest.main()
