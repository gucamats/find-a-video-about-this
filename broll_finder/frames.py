"""Pick frame moments, extract labeled frames and tile them into 3x3 grids."""

import json
import re
import time
from pathlib import Path

from . import tools
from .transcript import find_hits, theme_terms

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def mmss(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def parse_scdet(stderr):
    """Cut times from `scdet=...:sc_pass=1,showinfo` stderr."""
    times = []
    for line in stderr.splitlines():
        if "showinfo" in line:
            match = re.search(r"pts_time:\s*(-?[0-9.]+)", line)
            if match:
                times.append(float(match.group(1)))
    return times


def merge_cuts(cuts, min_gap=0.5):
    """Sorted cuts, dropping any closer than `min_gap` to the previous kept one."""
    merged = []
    for cut in sorted(cuts):
        if not merged or cut - merged[-1] >= min_gap:
            merged.append(cut)
    return merged


def choose_mode(duration, speech_seconds, cuts, hits, min_coverage=0.3,
                dense_cuts_per_min=15):
    """Pick how to choose frame moments. Returns (mode, human-readable reason).

    Measured on the reference videos: news clips had ~100 % speech and
    0.3-0.7 cuts/min; motion-design clips had 34-55 cuts/min; a lyric video
    had 1.3 cuts/min. The default threshold of 15/min sits in that gap and
    has not been calibrated beyond these few videos.
    """
    coverage = speech_seconds / duration if duration else 0.0
    per_min = cuts / (duration / 60) if duration else 0.0
    facts = f"speech coverage {coverage:.0%}, {cuts} cuts ({per_min:.1f}/min), {hits} theme hits"
    if per_min >= dense_cuts_per_min:
        mode, why = "cuts", "dense cuts"
    elif hits and coverage >= min_coverage:
        mode, why = "speech", "speech-driven video"
    else:
        mode, why = "interval", "no speech-driven theme hits and few cuts"
    if hits and mode != "speech":
        why += "; frames at the theme hits are included too"
    return mode, f"{facts}: {why}"


def cap_evenly(items, n):
    """At most `n` items, evenly spread, keeping first and last."""
    if len(items) <= n:
        return list(items)
    if n == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def _spaced(points, gap):
    kept = []
    for p in sorted(points):
        if not kept or p - kept[-1] >= gap:
            kept.append(p)
    return kept


def select_moments(mode, duration, cuts, hit_ranges, max_frames, interval=2.0,
                   cut_offset=0.3, min_spacing=1.0):
    """Frame times in seconds.

    Theme hits always count: every `interval` s inside each hit range is a
    frame, whatever the mode, and these frames are kept first under the cap.
    On top of them, the mode adds:
    - cuts: the opening shot plus one frame `cut_offset` after each merged cut.
    - speech: cuts that fall inside a hit range.
    - interval: every `interval` s across the video.
    Mode frames closer than `min_spacing` to a hit frame are skipped, and the
    remaining slots up to `max_frames` are spread evenly over them.
    """
    samples = []
    for start, end in hit_ranges:
        t = start
        while t < min(end, duration):
            samples.append(round(t, 3))
            t += interval
    hit_frames = cap_evenly(_spaced(samples, min_spacing), max_frames)

    base = []
    if mode == "cuts":
        merged = merge_cuts(cuts)
        if not merged or merged[0] >= 0.5:
            base.append(cut_offset)
        base += [c + cut_offset for c in merged if c + cut_offset < duration]
    elif mode == "speech":
        base = [c + cut_offset for c in merge_cuts(cuts)
                if any(s <= c < e for s, e in hit_ranges) and c + cut_offset < duration]
    elif mode == "interval":
        t = 0.0
        while t < duration:
            base.append(t)
            t += interval
    else:
        raise ValueError(f"unknown mode: {mode}")
    base = [round(b, 3) for b in base
            if all(abs(b - h) >= min_spacing for h in hit_frames)]
    return sorted(hit_frames + cap_evenly(base, max_frames - len(hit_frames)))


def drawtext_escape(value):
    """Quote a value for an ffmpeg drawtext option.

    The filtergraph is parsed twice: the quotes survive the first pass, the
    `\\:` the second. Backslashes become slashes so Windows paths work.
    """
    return "'" + value.replace("\\", "/").replace(":", "\\:") + "'"


def default_font():
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None  # ffmpeg falls back to fontconfig's default font


def detect_cuts(video, threshold=10):
    # `select=gt(scene,0.3)` returned no frames on ffmpeg 9.0.2; scdet works.
    result = tools.run(["ffmpeg", "-hide_banner", "-an", "-i", str(video), "-vf",
                        f"scdet=threshold={threshold}:sc_pass=1,showinfo",
                        "-f", "null", "-"])
    if result.returncode != 0:
        raise RuntimeError(f"scene detection failed: {tools.last_error(result.stderr)}")
    return parse_scdet(result.stderr)


def extract_frames(video, moments, frames_dir, font=None, width=640):
    """One JPEG per moment, `MM:SS` drawn top-left. Returns [(time, path)]."""
    font_opt = f"fontfile={drawtext_escape(font)}:" if font else ""
    produced = []
    for i, t in enumerate(moments, start=1):
        out = Path(frames_dir) / f"frame_{i:03d}.jpg"
        vf = (f"scale={width}:-2,drawtext={font_opt}text={drawtext_escape(mmss(t))}"
              ":fontcolor=yellow:fontsize=28:box=1:boxcolor=black@0.6:boxborderw=6:x=8:y=8")
        result = tools.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                            "-q:v", "3", "-vf", vf, str(out)])
        if result.returncode != 0:
            raise RuntimeError(f"frame at {mmss(t)} failed: {tools.last_error(result.stderr)}")
        if out.is_file():  # a seek right at the end can yield no frame
            produced.append((t, out))
    return produced


def make_grids(frame_paths, grids_dir, cols=3, rows=3):
    """Tile frames into grids of cols x rows. Returns the grid paths."""
    per_grid = cols * rows
    grids = []
    for g in range(0, len(frame_paths), per_grid):
        chunk = frame_paths[g:g + per_grid]
        out = Path(grids_dir) / f"grid_{g // per_grid + 1:02d}.jpg"
        inputs = []
        for path in chunk:
            inputs += ["-i", str(path)]
        labels = "".join(f"[{i}:v]" for i in range(len(chunk)))
        graph = (f"{labels}concat=n={len(chunk)}:v=1:a=0,"
                 f"tile={cols}x{rows}:padding=4:color=white")
        result = tools.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            *inputs, "-filter_complex", graph, "-frames:v", "1",
                            "-q:v", "3", str(out)])
        if result.returncode != 0 or not out.is_file():
            raise RuntimeError(f"grid {out.name} failed: {tools.last_error(result.stderr)}")
        grids.append(out)
    return grids


def frames(video_dir, theme, terms=None, mode="auto", max_frames=36, interval=2.0,
           scdet_threshold=10, font=None):
    """Write frames, grids and `frames.json` into the video folder."""
    started = time.monotonic()
    video_dir = Path(video_dir)
    video = video_dir / "video.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"{video} not found (run download first)")
    duration = tools.probe_duration(video)
    if duration is None:
        raise RuntimeError(f"could not read the duration of {video}")

    transcript_path = video_dir / "transcript.json"
    segments = []
    if transcript_path.is_file():
        segments = json.loads(transcript_path.read_text(encoding="utf-8"))["segments"]
    terms = terms or theme_terms(theme)
    hits = find_hits(segments, terms)
    speech_seconds = sum(s["end"] - s["start"] for s in segments)

    cuts = detect_cuts(video, scdet_threshold)
    if mode == "auto":
        mode, reason = choose_mode(duration, speech_seconds, len(cuts), len(hits))
    else:
        reason = "set on the command line"
    moments = select_moments(mode, duration, cuts,
                             [(h["start"], h["end"]) for h in hits], max_frames, interval)

    frames_dir, grids_dir = video_dir / "frames", video_dir / "grids"
    frames_dir.mkdir(exist_ok=True)
    grids_dir.mkdir(exist_ok=True)
    for old in [*frames_dir.glob("frame_*.jpg"), *grids_dir.glob("grid_*.jpg")]:
        old.unlink()
    font = font or default_font()
    produced = extract_frames(video, moments, frames_dir, font)
    grids = make_grids([p for _, p in produced], grids_dir)

    per_grid = 9
    data = {
        "video": str(video.resolve()),
        "theme": theme,
        "terms": terms,
        "duration": duration,
        "transcript": str(transcript_path.resolve()) if transcript_path.is_file() else None,
        "mode": mode,
        "mode_reason": reason,
        "cuts": [round(c, 3) for c in cuts],
        "theme_hits": hits,
        "grids": [str(g.resolve()) for g in grids],
        "frames": [{
            "index": i,
            "time": t,
            "mmss": mmss(t),
            "path": str(p.resolve()),
            "grid": str(grids[(i - 1) // per_grid].resolve()),
            # Filled by whoever looks at the grids (Claude), not by this tool.
            "on_screen_text": "",
            "description": "",
            "shows_theme": None,
        } for i, (t, p) in enumerate(produced, start=1)],
        "elapsed_s": round(time.monotonic() - started, 1),
    }
    (video_dir / "frames.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
