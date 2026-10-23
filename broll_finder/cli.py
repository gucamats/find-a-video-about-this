"""Command line: python -m broll_finder <command> ..."""

import argparse
import json
import sys
from pathlib import Path

from . import download as dl
from .frames import frames
from .pipeline import new_request_dir, run
from .search import search
from .transcript import transcribe


def _terms(value):
    return [t.strip() for t in value.split(",") if t.strip()] if value else None


def build_parser():
    p = argparse.ArgumentParser(
        prog="broll_finder",
        description="Find b-roll on a theme: search, download, transcribe and "
                    "frame-grab videos into a per-request folder.")
    p.add_argument("--out", default="output",
                   help="folder that holds the request folders (default: ./output)")
    p.add_argument("--accept-language", default="pt-BR",
                   help="Accept-Language header sent to the sites (default: pt-BR)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="search YouTube, print JSON results")
    s.add_argument("terms")
    s.add_argument("-n", type=int, default=10, help="number of results (default: 10)")
    s.add_argument("--full", action="store_true",
                   help="fetch each video page to get the upload date (slower)")

    d = sub.add_parser("download", help="download links at up to 720p for analysis")
    d.add_argument("urls", nargs="+")
    d.add_argument("--request", help="request folder name (default: timestamp)")
    d.add_argument("--max-height", type=int, default=720)

    c = sub.add_parser("clip", help="download only an excerpt at max quality")
    c.add_argument("url")
    c.add_argument("--start", required=True, help="seconds or [HH:]MM:SS")
    c.add_argument("--end", required=True, help="seconds or [HH:]MM:SS")
    c.add_argument("--request", help="request folder name (default: timestamp)")
    c.add_argument("--keyframes", action="store_true",
                   help="re-encode around the cuts for frame-exact edges (slower)")

    def transcribe_opts(parser):
        parser.add_argument("--model", default="small", help="faster-whisper model (default: small)")
        parser.add_argument("--language", default="pt", help="speech language (default: pt)")
        parser.add_argument("--no-subs", action="store_true",
                            help="skip YouTube subtitles, always transcribe locally")

    t = sub.add_parser("transcribe", help="write transcript.json for a downloaded video")
    t.add_argument("video_dir", help="folder with video.mp4 (made by download)")
    transcribe_opts(t)
    t.add_argument("--sub-langs", default="pt-BR,pt",
                   help="subtitle languages to try, in order (default: pt-BR,pt)")

    def frame_opts(parser):
        parser.add_argument("--terms", help="comma-separated keywords (default: words of the theme)")
        parser.add_argument("--mode", default="auto", choices=["auto", "speech", "cuts", "interval"])
        parser.add_argument("--max-frames", type=int, default=36)
        parser.add_argument("--interval", type=float, default=2.0,
                            help="seconds between frames when sampling (default: 2)")
        parser.add_argument("--font", help="TTF font for the timestamp (default: system bold font)")

    f = sub.add_parser("frames", help="extract labeled frames and 3x3 grids")
    f.add_argument("video_dir")
    f.add_argument("--theme", required=True)
    frame_opts(f)

    r = sub.add_parser("run", help="search -> download -> transcribe -> frames -> report")
    r.add_argument("theme")
    r.add_argument("-n", type=int, default=3, help="videos to process (default: 3)")
    r.add_argument("--query", help="search query (default: the theme)")
    r.add_argument("--max-height", type=int, default=720)
    transcribe_opts(r)
    frame_opts(r)
    return p


def _print(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    a = build_parser().parse_args(argv)
    lang = a.accept_language
    if a.command == "search":
        _print(search(a.terms, a.n, lang, a.full))
    elif a.command == "download":
        request_dir = new_request_dir(a.out, a.request or "download")
        results = [dl.download(u, request_dir, a.max_height, lang) for u in a.urls]
        _print(results)
        return 1 if any(r["status"] != "ok" for r in results) else 0
    elif a.command == "clip":
        request_dir = new_request_dir(a.out, a.request or "clip")
        result = dl.clip(a.url, a.start, a.end, request_dir, a.keyframes, lang)
        _print(result)
        return 0 if result["status"] == "ok" else 1
    elif a.command == "transcribe":
        data = transcribe(a.video_dir, a.model, a.language, not a.no_subs, a.sub_langs, lang)
        _print({k: v for k, v in data.items() if k not in ("segments", "dropped")})
    elif a.command == "frames":
        data = frames(a.video_dir, a.theme, _terms(a.terms), a.mode, a.max_frames,
                      a.interval, font=a.font)
        summary = {k: data[k] for k in ("mode", "mode_reason", "grids", "elapsed_s")}
        summary["frames"] = len(data["frames"])
        summary["frames_json"] = str((Path(a.video_dir) / "frames.json").resolve())
        _print(summary)
    elif a.command == "run":
        report = run(a.theme, a.out, a.n, a.query, _terms(a.terms), lang, a.max_height,
                     a.model, a.language, not a.no_subs, a.mode, a.max_frames,
                     a.interval, a.font)
        print(f"{report['request_dir']}/report.md")
    return 0
