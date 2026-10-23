import json
import subprocess

from broll_finder import tools
from broll_finder.search import parse_search_lines, search


def entry(**kw):
    base = {
        "_type": "url", "ie_key": "Youtube", "id": "abc123",
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "Título em português", "channel": "Canal",
        "duration": 71, "timestamp": None,
    }
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def test_parses_one_result_per_json_line():
    out = entry() + "\n" + entry(id="xyz", url="https://www.youtube.com/watch?v=xyz") + "\n"
    results = parse_search_lines(out)
    assert [r["id"] for r in results] == ["abc123", "xyz"]
    assert results[0] == {
        "id": "abc123",
        "url": "https://www.youtube.com/watch?v=abc123",
        "channel": "Canal",
        "duration": 71,
        "upload_date": None,
        "title": "Título em português",
        "source": "youtube",
    }


def test_formats_upload_date_when_present():
    [r] = parse_search_lines(entry(upload_date="20261022"))
    assert r["upload_date"] == "2026-10-22"


def test_falls_back_to_uploader_and_webpage_url():
    line = entry(channel=None, uploader="Uploader", url=None,
                 webpage_url="https://www.youtube.com/watch?v=abc123")
    [r] = parse_search_lines(line)
    assert r["channel"] == "Uploader"
    assert r["url"] == "https://www.youtube.com/watch?v=abc123"


def test_ignores_blank_and_non_json_lines():
    out = "\nWARNING: something\n" + entry() + "\n   \n"
    assert len(parse_search_lines(out)) == 1


def test_search_query_comes_after_double_dash(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, entry() + "\n", "")

    monkeypatch.setattr(tools, "run", run)
    assert len(search("-x quebra de sigilo", n=3)) == 1
    assert calls[0][-2:] == ["--", "ytsearch3:-x quebra de sigilo"]
