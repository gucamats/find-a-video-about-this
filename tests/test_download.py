import json
import subprocess
from pathlib import Path

import pytest

from findavideo import cli, tools
from findavideo.download import ANALYSIS_FORMAT, check_duration, parse_time

BAD = "https://www.youtube.com/watch?v=bad"
GOOD = "https://www.youtube.com/watch?v=good"


def test_duration_within_tolerance_passes():
    ok, _ = check_duration(actual=37.9, expected=36)
    assert ok


def test_duration_outside_tolerance_fails_with_reason():
    ok, reason = check_duration(actual=20.0, expected=36)
    assert not ok
    assert "20.0" in reason and "36" in reason


def test_tolerance_is_configurable():
    assert check_duration(actual=40, expected=36, tolerance=5)[0]
    assert not check_duration(actual=40, expected=36, tolerance=2)[0]


def test_unknown_platform_duration_passes_but_says_so():
    ok, reason = check_duration(actual=12.0, expected=None)
    assert ok
    assert "no duration" in reason


def test_unreadable_file_duration_fails():
    ok, _ = check_duration(actual=None, expected=36)
    assert not ok


def test_parse_time_accepts_seconds_mmss_and_hhmmss():
    assert parse_time("90") == 90.0
    assert parse_time("1:30.5") == 90.5
    assert parse_time("01:02:03") == 3723.0


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time("abc")


def fake_yt_dlp(monkeypatch, behaviour, file_duration=36.0):
    """Replace yt-dlp: behaviour maps url -> ("ok", platform_duration) or ("fail", stderr)."""
    calls = []

    def run(cmd):
        calls.append(cmd)
        url = cmd[-1]
        kind, value = behaviour[url]
        if kind == "fail":
            return subprocess.CompletedProcess(cmd, 1, "", value)
        vid = url.rsplit("=", 1)[-1]
        template = cmd[cmd.index("-o") + 1]
        path = Path(template.replace("%(id)s", vid).replace("%(ext)s", "mp4"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        path.with_suffix(".info.json").write_text(
            json.dumps({"id": vid, "duration": value, "extractor_key": "Youtube"}),
            encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, f"{path}\n", "")

    monkeypatch.setattr(tools, "run", run)
    monkeypatch.setattr(tools, "probe_duration", lambda path: file_duration)
    return calls


def test_failing_link_becomes_error_and_next_link_still_downloads(tmp_path, monkeypatch, capsys):
    calls = fake_yt_dlp(monkeypatch, {
        BAD: ("fail", "WARNING: x\nERROR: [youtube] bad: This video is unavailable\n"),
        GOOD: ("ok", 36),
    })
    code = cli.main(["--out", str(tmp_path), "download", BAD, GOOD])
    out = json.loads(capsys.readouterr().out)
    assert len(calls) == 2
    assert out[0]["status"] == "error"
    assert out[0]["error"] == "ERROR: [youtube] bad: This video is unavailable"
    assert out[1]["status"] == "ok" and out[1]["id"] == "good"
    assert code == 1


def test_duration_mismatch_marks_download_as_error(tmp_path, monkeypatch, capsys):
    fake_yt_dlp(monkeypatch, {GOOD: ("ok", 60)}, file_duration=36.0)
    cli.main(["--out", str(tmp_path), "download", GOOD])
    [entry] = json.loads(capsys.readouterr().out)
    assert entry["status"] == "error"
    assert "duration mismatch" in entry["error"]
    assert Path(entry["video"]).is_file()  # the file stays for inspection


def test_download_command_ends_options_before_url_and_remuxes_to_mp4(tmp_path, monkeypatch, capsys):
    calls = fake_yt_dlp(monkeypatch, {GOOD: ("ok", 36)})
    cli.main(["--out", str(tmp_path), "download", GOOD])
    cmd = calls[0]
    assert cmd[-2:] == ["--", GOOD]
    assert cmd[cmd.index("--remux-video") + 1] == "mp4"


def test_clip_command_ends_options_before_url(tmp_path, monkeypatch, capsys):
    calls = fake_yt_dlp(monkeypatch, {GOOD: ("ok", None)}, file_duration=10.0)
    code = cli.main(["--out", str(tmp_path), "clip", GOOD, "--start", "5", "--end", "15"])
    assert calls[0][-2:] == ["--", GOOD]
    assert code == 0


def test_analysis_format_never_falls_back_to_unbounded_resolution():
    alternatives = ANALYSIS_FORMAT.format(h=720).split("/")
    for alternative in alternatives:
        for part in alternative.split("+"):
            if part != "ba":
                assert "<=" in part, alternative
    # Unknown resolution is allowed only in the last, `<=?` alternative.
    assert "[height<=?720][width<=?720]" in alternatives[-1]
