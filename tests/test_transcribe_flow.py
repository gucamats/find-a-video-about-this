import json
import subprocess
from pathlib import Path

import pytest

from findavideo import tools, transcript

URL = "https://www.youtube.com/watch?v=abc"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nlegenda\n"


def make_video_dir(tmp_path, extractor="Youtube"):
    d = tmp_path / "abc"
    d.mkdir()
    (d / "video.mp4").write_bytes(b"")
    (d / "video.info.json").write_text(
        json.dumps({"extractor_key": extractor, "webpage_url": URL}), encoding="utf-8")
    return d


def patch_sources(monkeypatch, subtitles):
    """subtitles: a segment list to return, or an exception to raise."""
    calls = {"subs": 0, "whisper": 0}

    def fake_subs(url, video_dir, sub_langs, accept_language):
        calls["subs"] += 1
        if isinstance(subtitles, Exception):
            raise subtitles
        return "pt-BR", subtitles

    def fake_whisper(video, model_size, language):
        calls["whisper"] += 1
        segs = [{"start": 0.0, "end": 2.0, "text": "fala local", "no_speech_prob": 0.1,
                 "avg_logprob": -0.2, "compression_ratio": 1.2}]
        return segs, {"model_load_s": 1.0, "transcribe_s": 2.0}

    monkeypatch.setattr(transcript, "youtube_subtitles", fake_subs)
    monkeypatch.setattr(transcript, "whisper_segments", fake_whisper)
    monkeypatch.setattr(tools, "probe_duration", lambda path: 10.0)
    return calls


def test_subtitle_failure_falls_back_to_whisper(tmp_path, monkeypatch):
    calls = patch_sources(monkeypatch, RuntimeError("ERROR: HTTP Error 429: Too Many Requests"))
    data = transcript.transcribe(make_video_dir(tmp_path))
    assert calls == {"subs": 1, "whisper": 1}
    assert data["source"] == "faster-whisper" and data["model"] == "small"
    assert "429" in data["subtitle_error"]
    assert data["segments"][0]["text"] == "fala local"
    saved = json.loads((tmp_path / "abc" / "transcript.json").read_text(encoding="utf-8"))
    assert saved["source"] == "faster-whisper"
    assert set(saved["elapsed"]) == {"subtitles_s", "model_load_s", "transcribe_s"}


def test_youtube_subtitles_are_used_when_present(tmp_path, monkeypatch):
    calls = patch_sources(monkeypatch, [{"start": 1.0, "end": 2.0, "text": "legenda"}])
    data = transcript.transcribe(make_video_dir(tmp_path))
    assert calls == {"subs": 1, "whisper": 0}
    assert data["source"] == "youtube-subtitles" and data["model"] is None
    assert data["subtitle_language"] == "pt-BR"
    assert data["segments"] == [{"start": 1.0, "end": 2.0, "text": "legenda", "flags": []}]


def test_non_youtube_video_goes_straight_to_whisper(tmp_path, monkeypatch):
    calls = patch_sources(monkeypatch, [{"start": 1.0, "end": 2.0, "text": "x"}])
    data = transcript.transcribe(make_video_dir(tmp_path, extractor="TikTok"))
    assert calls == {"subs": 0, "whisper": 1}
    assert data["source"] == "faster-whisper" and data["subtitle_error"] is None


def test_no_subs_option_skips_subtitles(tmp_path, monkeypatch):
    calls = patch_sources(monkeypatch, [{"start": 1.0, "end": 2.0, "text": "x"}])
    transcript.transcribe(make_video_dir(tmp_path), use_subtitles=False)
    assert calls == {"subs": 0, "whisper": 1}


def fake_subs_download(monkeypatch, langs_written, returncode=0, stderr=""):
    calls = []

    def run(cmd):
        calls.append(cmd)
        base = cmd[cmd.index("-o") + 1]
        for lang in langs_written:
            Path(f"{base}.{lang}.vtt").write_text(VTT, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)

    monkeypatch.setattr(tools, "run", run)
    return calls


def test_youtube_subtitles_follow_language_order(tmp_path, monkeypatch):
    fake_subs_download(monkeypatch, ["pt", "pt-BR"])
    assert transcript.youtube_subtitles(URL, tmp_path, "pt-BR,pt")[0] == "pt-BR"
    assert transcript.youtube_subtitles(URL, tmp_path, "pt,pt-BR")[0] == "pt"


def test_youtube_subtitles_fall_to_next_language(tmp_path, monkeypatch):
    calls = fake_subs_download(monkeypatch, ["pt"])
    lang, segments = transcript.youtube_subtitles(URL, tmp_path, "pt-BR,pt")
    assert lang == "pt" and segments[0]["text"] == "legenda"
    assert calls[0][-2:] == ["--", URL]


def test_youtube_subtitles_none_available(tmp_path, monkeypatch):
    fake_subs_download(monkeypatch, [])
    with pytest.raises(RuntimeError, match="no uploaded subtitles in pt-BR, pt"):
        transcript.youtube_subtitles(URL, tmp_path, "pt-BR,pt")


def test_youtube_subtitles_yt_dlp_error(tmp_path, monkeypatch):
    fake_subs_download(monkeypatch, [], returncode=1,
                       stderr="ERROR: Unable to download video subtitles: HTTP Error 429: Too Many Requests\n")
    with pytest.raises(RuntimeError, match="HTTP Error 429"):
        transcript.youtube_subtitles(URL, tmp_path, "pt-BR,pt")
