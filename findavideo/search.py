"""YouTube search through yt-dlp, no API key."""

import json

from . import tools


def parse_search_lines(output):
    """Turn yt-dlp `-j` output (one JSON object per line) into result dicts."""
    results = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        date = entry.get("upload_date")
        source = entry.get("ie_key") or entry.get("extractor_key")
        results.append({
            "id": entry.get("id"),
            "url": entry.get("url") or entry.get("webpage_url"),
            "channel": entry.get("channel") or entry.get("uploader"),
            "duration": entry.get("duration"),
            "upload_date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if date else None,
            "title": entry.get("title"),
            "source": source.lower() if source else None,
        })
    return results


def search(terms, n=10, accept_language="pt-BR", full=False):
    """Search YouTube. The fast (flat) mode has no upload date; `full` fetches
    each video's page to get it, at roughly 2 s per result."""
    args = ["-j"]
    if not full:
        args.append("--flat-playlist")
    args += ["--", f"ytsearch{n}:{terms}"]
    result = tools.run(tools.yt_dlp(*args, accept_language=accept_language))
    results = parse_search_lines(result.stdout)
    if not results and result.returncode != 0:
        raise RuntimeError(f"search failed: {tools.last_error(result.stderr)}")
    return results
