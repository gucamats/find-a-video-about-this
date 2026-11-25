"""Download a whole video for analysis, or an approved excerpt at max quality."""

import json
import time
from pathlib import Path

from . import tools

# Landscape first, then vertical video (TikTok: 720x1280 is "720p"), then
# formats whose resolution the site does not report (`<=?` lets an unknown
# value pass but still rejects a known one above the limit).
ANALYSIS_FORMAT = ("bv*[height<={h}]+ba/b[height<={h}]"
                   "/bv*[width<={h}]+ba/b[width<={h}]"
                   "/bv*[height<=?{h}][width<=?{h}]+ba/b[height<=?{h}][width<=?{h}]")
MAX_FORMAT = "bv*+ba/b"


def check_duration(actual, expected, tolerance=2.0, reference="platform"):
    """Compare the file duration (ffprobe) with the expected one."""
    if actual is None:
        return False, "could not read the file duration with ffprobe"
    if expected is None:
        return True, f"{reference} reported no duration; file has {actual:.1f} s"
    if abs(actual - expected) <= tolerance:
        return True, f"file {actual:.1f} s matches {reference} {expected} s"
    return False, (f"duration mismatch: file {actual:.1f} s vs {reference} "
                   f"{expected} s (tolerance {tolerance} s)")


def parse_time(value):
    """Seconds from '90', '1:30.5' or '01:02:03'."""
    seconds = 0.0
    for part in str(value).strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def _fetch(url, out_template, fmt, extra_args, accept_language):
    """Run yt-dlp and return the final file path. Raises on failure."""
    # --remux-video: a single-file fallback (e.g. webm) still ends up as .mp4.
    cmd = tools.yt_dlp(
        "-f", fmt, "--merge-output-format", "mp4", "--remux-video", "mp4",
        "--no-playlist", "-o", out_template, "--print", "after_move:filepath",
        *extra_args, "--", url,
        accept_language=accept_language,
    )
    result = tools.run(cmd)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0 or not lines:
        raise RuntimeError(tools.last_error(result.stderr))
    path = Path(lines[-1])
    if not path.is_file():
        raise RuntimeError(f"yt-dlp reported {path} but the file does not exist")
    return path


def download(url, request_dir, max_height=720, accept_language="pt-BR", tolerance=2.0):
    """Download `url` at up to `max_height` into `request_dir/<id>/video.mp4`.

    Never raises: a failure comes back as {"status": "error", "error": reason}.
    """
    entry = {"url": url, "status": "error", "error": None}
    started = time.monotonic()
    try:
        template = str(Path(request_dir) / "%(id)s" / "video.%(ext)s")
        video = _fetch(url, template, ANALYSIS_FORMAT.format(h=max_height),
                       ["--write-info-json"], accept_language)
        info_path = video.with_suffix(".info.json")
        info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
        file_duration = tools.probe_duration(video)
        ok, check = check_duration(file_duration, info.get("duration"), tolerance)
        date = info.get("upload_date")
        entry.update({
            "id": info.get("id"),
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "source": (info.get("extractor_key") or "").lower() or None,
            "upload_date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if date else None,
            "duration": info.get("duration"),
            "video_dir": str(video.parent.resolve()),
            "video": str(video.resolve()),
            "file_duration": file_duration,
            "duration_check": check,
            "status": "ok" if ok else "error",
            "error": None if ok else check,
        })
    except Exception as exc:  # one bad link must not stop the others
        entry["error"] = str(exc)
    entry["elapsed_s"] = round(time.monotonic() - started, 1)
    return entry


def clip(url, start, end, request_dir, keyframes=False, accept_language="pt-BR",
         tolerance=2.0):
    """Download only `start`-`end` (seconds or [HH:]MM:SS) at max quality."""
    entry = {"url": url, "start": start, "end": end, "status": "error", "error": None}
    started = time.monotonic()
    try:
        s, e = parse_time(start), parse_time(end)
        if e <= s:
            raise ValueError(f"end ({end}) must be after start ({start})")
        name = f"clip_{s:.0f}-{e:.0f}.%(ext)s"
        template = str(Path(request_dir) / "%(id)s" / name)
        extra = ["--download-sections", f"*{s}-{e}"]
        if keyframes:
            extra.append("--force-keyframes-at-cuts")
        video = _fetch(url, template, MAX_FORMAT, extra, accept_language)
        file_duration = tools.probe_duration(video)
        ok, check = check_duration(file_duration, e - s, tolerance, "requested range")
        entry.update({
            "video": str(video.resolve()),
            "file_duration": file_duration,
            "duration_check": check,
            "status": "ok" if ok else "error",
            "error": None if ok else check,
        })
    except Exception as exc:
        entry["error"] = str(exc)
    entry["elapsed_s"] = round(time.monotonic() - started, 1)
    return entry
