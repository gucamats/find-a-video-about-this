"""Thin wrappers around the external programs: yt-dlp, ffmpeg, ffprobe."""

import subprocess
import sys


def run(cmd):
    """Run a command and capture its output as UTF-8 text."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def yt_dlp(*args, accept_language=None):
    """Build a yt-dlp command using the yt-dlp installed next to this Python."""
    cmd = [sys.executable, "-m", "yt_dlp"]
    if accept_language:
        # Without these, YouTube returns English machine-translated titles.
        # The header alone was not enough for flat search; `lang` takes a
        # primary code ("pt", not "pt-BR").
        cmd += ["--add-headers", f"Accept-Language:{accept_language}",
                "--extractor-args", f"youtube:lang={accept_language.split('-')[0]}"]
    return cmd + list(args)


def last_error(stderr):
    """The most useful line of a failed command's stderr."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR")]
    if errors:
        return errors[-1]
    return lines[-1] if lines else "unknown error (no output)"


def probe_duration(path):
    """Duration of a media file in seconds, or None if ffprobe cannot read it."""
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
