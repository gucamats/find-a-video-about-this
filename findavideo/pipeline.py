"""End to end: search -> download -> transcribe -> frames, plus the report."""

import json
from datetime import datetime
from pathlib import Path

from .download import download
from .frames import frames, mmss
from .search import search
from .transcript import normalize_text, theme_terms, transcribe


def slugify(text, max_len=50):
    return "-".join(normalize_text(text).split())[:max_len].strip("-")


def new_request_dir(out_dir, name):
    path = Path(out_dir) / f"{datetime.now():%Y-%m-%d_%H%M%S}-{slugify(name) or 'request'}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run(theme, out_dir="output", n=3, query=None, terms=None, accept_language="pt-BR",
        max_height=720, model_size="small", language="pt", use_subtitles=True,
        mode="auto", max_frames=36, interval=2.0, font=None):
    """Process the top `n` search results for `theme`. Returns the report dict."""
    request_dir = new_request_dir(out_dir, theme)
    report = {
        "theme": theme,
        "query": query or theme,
        "terms": terms or theme_terms(theme),
        "created": datetime.now().isoformat(timespec="seconds"),
        "request_dir": str(request_dir.resolve()),
        "search_error": None,
        "videos": [],
    }
    try:
        results = search(report["query"], n, accept_language)
    except Exception as exc:
        report["search_error"] = str(exc)
        results = []
    write_report(report, request_dir)

    for result in results:
        video = {**result, "status": "error", "errors": [], "timings": {}}
        report["videos"].append(video)
        got = download(result["url"], request_dir, max_height, accept_language)
        video["timings"]["download_s"] = got["elapsed_s"]
        video.update({k: got[k] for k in ("video_dir", "duration_check", "upload_date")
                      if got.get(k)})
        if got["status"] != "ok":
            video["errors"].append(f"download: {got['error']}")
            write_report(report, request_dir)
            continue
        try:
            t = transcribe(got["video_dir"], model_size, language, use_subtitles,
                           accept_language=accept_language)
            video["timings"]["transcribe_s"] = sum(t["elapsed"].values())
            video["transcript"] = {
                "path": str(Path(got["video_dir"], "transcript.json")),
                "source": t["source"], "model": t["model"],
                "subtitle_error": t["subtitle_error"], **t["counts"],
            }
        except Exception as exc:  # frames can still come from cuts
            video["errors"].append(f"transcribe: {exc}")
        try:
            f = frames(got["video_dir"], theme, report["terms"], mode, max_frames,
                       interval, font=font)
            video["timings"]["frames_s"] = f["elapsed_s"]
            video.update({
                "frames_json": str(Path(got["video_dir"], "frames.json")),
                "frame_mode": f["mode"], "frame_mode_reason": f["mode_reason"],
                "frame_count": len(f["frames"]), "grids": f["grids"],
                "theme_hits": f["theme_hits"],
            })
        except Exception as exc:
            video["errors"].append(f"frames: {exc}")
        video["status"] = "ok" if not video["errors"] else "partial"
        write_report(report, request_dir)
    return report


def _md(report):
    lines = [f"# B-roll report: {report['theme']}", "",
             f"- Created: {report['created']}",
             f"- Search query: `{report['query']}`",
             f"- Theme terms: {', '.join(report['terms'])}",
             f"- Folder: `{report['request_dir']}`"]
    if report["search_error"]:
        lines.append(f"- **Search error:** {report['search_error']}")
    lines.append("")
    for i, v in enumerate(report["videos"], start=1):
        duration = mmss(v["duration"]) if v.get("duration") else "?"
        lines += [f"## {i}. {v.get('title') or v['url']}", "",
                  f"- URL: {v['url']}",
                  f"- Channel: {v.get('channel') or '?'} | duration {duration} | "
                  f"uploaded {v.get('upload_date') or '?'} | source {v.get('source') or '?'}",
                  f"- Status: **{v['status']}**",
                  "- Timings: " + (", ".join(f"{k} {s} s" for k, s in v["timings"].items()) or "-")]
        if v.get("duration_check"):
            lines.append(f"- Duration check: {v['duration_check']}")
        t = v.get("transcript")
        if t:
            via = f"{t['source']}" + (f" ({t['model']})" if t["model"] else "")
            lines.append(f"- Transcript: {via}, {t['kept']} segments kept, "
                         f"{t['dropped']} dropped as silence, {t['flagged']} flagged "
                         f"-> `{t['path']}`")
            if t["subtitle_error"]:
                lines.append(f"  - Subtitles not used: {t['subtitle_error']}")
        if "theme_hits" in v:
            lines.append(f"- Theme hits in speech: {len(v['theme_hits'])}")
            for h in v["theme_hits"]:
                lines.append(f"  - {mmss(h['start'])}-{mmss(h['end'])} "
                             f"({', '.join(h['matched'])}): {h['text']}")
        if v.get("grids"):
            lines.append(f"- Frames: {v['frame_count']} by `{v['frame_mode']}` "
                         f"({v['frame_mode_reason']})")
            lines.append(f"- Frame list to fill in: `{v['frames_json']}`")
            lines += [f"  - Grid: `{g}`" for g in v["grids"]]
        for err in v["errors"]:
            lines.append(f"- **Error:** {err}")
        lines.append("")
    return "\n".join(lines)


def write_report(report, request_dir):
    request_dir = Path(request_dir)
    (request_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (request_dir / "report.md").write_text(_md(report), encoding="utf-8")
