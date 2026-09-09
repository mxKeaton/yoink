#!/usr/bin/env python3
"""Minimal interactive YouTube provider for Yoink."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from shlex import join
from urllib.parse import urlsplit

import settings


def youtube_url(value):
    url = urlsplit(value)
    host = (url.hostname or "").lower()
    if (url.scheme not in ("http", "https") or url.username or url.password
            or not (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"))):
        raise ValueError("Enter a full https://youtube.com/… or https://youtu.be/… link.")
    if any(ord(char) < 32 for char in value):
        raise ValueError("The link contains control characters.")
    return value


def choose(title, options):
    print(f"\n{title}")
    for number, option in enumerate(options, 1):
        print(f"  {number}. {option}")
    while True:
        value = input("Choice [1]: ").strip() or "1"
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print("Choose one of the numbered options.")


def command(url, mode, output, fmt, quality, metadata=False, subtitles=False):
    args = ["yt-dlp", "--ignore-config", "--no-playlist", "--no-overwrites",
            "--paths", str(output), "--output", "%(title).180B [%(id)s].%(ext)s"]
    if mode == "Audio":
        args += ["-f", "bestaudio/best", "--extract-audio", "--audio-format", fmt,
                 "--audio-quality", quality]
    else:
        selector = "bv*+ba/b" if quality == "Best" else f"bv*[height<={quality}]+ba/b[height<={quality}]"
        args += ["-f", selector]
        if fmt != "auto":
            args += ["--merge-output-format", fmt, "--remux-video", fmt]
        if subtitles:
            args += ["--write-subs", "--sub-langs", "en.*", "--embed-subs"]
    if metadata:
        args += ["--embed-metadata"]
    return args + ["--", url]


def gui_command(options):
    """Validate popup input and reuse the same argument builder as the CLI."""
    url = youtube_url(options.get("url", "").strip())
    mode = options.get("mode", "Video")
    if mode not in ("Video", "Audio"):
        raise ValueError("Choose Video or Audio.")
    if options.get("action") == "formats":
        return ["yt-dlp", "--ignore-config", "--no-playlist", "--no-colors", "-F", "--", url]
    fmt = options.get("format", "auto" if mode == "Video" else "best")
    quality = options.get("quality", "Best" if mode == "Video" else "0")
    formats = ("auto", "mkv", "mp4") if mode == "Video" else ("best", "mp3", "m4a", "opus", "flac", "wav")
    qualities = ("Best", "2160", "1440", "1080", "720", "480") if mode == "Video" else ("0", "192K", "256K", "320K")
    if fmt not in formats or quality not in qualities:
        raise ValueError("Invalid format or quality selection.")
    kind = "video" if mode == "Video" else "audio"
    output = Path(options.get("output", "").strip() or settings.download_path(kind)).expanduser().absolute()
    output.mkdir(parents=True, exist_ok=True)
    args = command(url, mode, output, fmt, quality, options.get("metadata", False), options.get("subtitles", False))
    return args[:1] + ["--newline", "--no-colors", "--progress"] + args[1:]


def gui_main(payload):
    try:
        missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(name)]
        if missing:
            raise ValueError("Missing " + ", ".join(missing) + ". Install with: omarchy pkg add yt-dlp ffmpeg")
        args = gui_command(json.loads(payload))
        # Replace this process so the GUI's stop signal reaches yt-dlp directly.
        os.execvp(args[0], args)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1


def main():
    print("Yoink · YouTube\nCtrl+C cancels. Music/video available; other sources will come later.")
    missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        print("Missing: " + ", ".join(missing) + "\nInstall with: omarchy pkg add yt-dlp ffmpeg")
        return 1
    while True:
        try:
            url = youtube_url(input("\nYouTube link: ").strip())
            break
        except ValueError as error:
            print(error)
    mode = choose("Download as", ["Video", "Audio"])
    if choose("Inspect the available source formats?", ["Skip", "List formats (-F)"]) != "Skip":
        result = subprocess.run(["yt-dlp", "--ignore-config", "--no-playlist", "-F", "--", url])
        if result.returncode:
            print("Could not list formats. Check the link and yt-dlp output above.")
            return result.returncode
    if mode == "Audio":
        fmt = choose("Audio format (--audio-format)", ["best", "mp3", "m4a", "opus", "flac", "wav"])
        print("Encoding quality applies when converting; lossless output cannot restore lost source detail.")
        quality = choose("Audio quality (--audio-quality)", ["0", "192K", "256K", "320K"])
        subtitles = False
    else:
        quality = choose("Maximum video height (-f); no upscaling", ["Best", "2160", "1440", "1080", "720", "480"])
        fmt = choose("Container (merge/remux; auto keeps the source container)", ["auto", "mkv", "mp4"])
        subtitles = choose("Embed available English subtitles?", ["No", "Yes"]) == "Yes"
    metadata = choose("Embed metadata (--embed-metadata)?", ["No", "Yes"]) == "Yes"
    default = Path(settings.download_path("video" if mode == "Video" else "audio"))
    output = Path(input(f"Download directory [{default}]: ").strip() or default).expanduser().absolute()
    args = command(url, mode, output, fmt, quality, metadata, subtitles)
    print("\nCommand:\n" + join(args))
    if choose("Start download?", ["Download", "Cancel"]) == "Cancel":
        return 0
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(args)
    print(f"\nSaved to {output}" if result.returncode == 0 else "\nDownload failed. See yt-dlp output above.")
    return result.returncode


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gui":
        sys.exit(gui_main(sys.argv[2]))
    status = 0
    try:
        status = main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        status = 130
    except OSError as error:
        print(f"\nError: {error}", file=sys.stderr)
        status = 1
    if sys.stdin.isatty():
        try:
            input("\nPress Enter to close…")
        except (KeyboardInterrupt, EOFError):
            pass
    sys.exit(status)
