import json
from pathlib import Path

from findavideo import pipeline
from findavideo.pipeline import slugify


def test_slugify():
    assert slugify("Quebra de sigilo: Lula & Flávio!") == "quebra-de-sigilo-lula-flavio"
    assert len(slugify("a " * 100)) <= 50


def test_run_isolates_failures_per_video(tmp_path, monkeypatch):
    # a: transcription crashes; b: download fails; c: all fine; d: frames crash.
    results = [{"id": v, "url": f"https://v/{v}", "title": v, "channel": "c",
                "duration": 10, "upload_date": None, "source": "youtube"} for v in "abcd"]
    monkeypatch.setattr(pipeline, "search", lambda query, n, lang: results)

    def fake_download(url, request_dir, max_height, lang):
        vid = url.rsplit("/", 1)[-1]
        if vid == "b":
            return {"status": "error", "error": "ERROR: boom", "elapsed_s": 0.1}
        d = Path(request_dir) / vid
        d.mkdir()
        return {"status": "ok", "error": None, "elapsed_s": 0.1, "video_dir": str(d),
                "duration_check": "ok"}

    def fake_transcribe(video_dir, *args, **kwargs):
        if Path(video_dir).name == "a":
            raise RuntimeError("whisper crashed")
        return {"elapsed": {"transcribe_s": 1.0}, "source": "faster-whisper", "model": "small",
                "subtitle_error": None, "counts": {"kept": 1, "dropped": 0, "flagged": 0}}

    def fake_frames(video_dir, theme, terms, mode, max_frames, interval, font=None):
        if Path(video_dir).name == "d":
            raise RuntimeError("ffmpeg died")
        return {"elapsed_s": 0.5, "mode": "interval", "mode_reason": "r", "frames": [],
                "grids": [], "theme_hits": []}

    monkeypatch.setattr(pipeline, "download", fake_download)
    monkeypatch.setattr(pipeline, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipeline, "frames", fake_frames)

    report = pipeline.run("tema", out_dir=tmp_path, n=4)

    by_id = {v["id"]: v for v in report["videos"]}
    assert {k: v["status"] for k, v in by_id.items()} == {
        "a": "partial", "b": "error", "c": "ok", "d": "partial"}
    assert by_id["a"]["errors"] == ["transcribe: whisper crashed"]
    assert by_id["a"]["frame_mode"] == "interval"  # frames still ran after the crash
    assert by_id["b"]["errors"] == ["download: ERROR: boom"]
    assert by_id["d"]["errors"] == ["frames: ffmpeg died"]

    request_dir = Path(report["request_dir"])
    saved = json.loads((request_dir / "report.json").read_text(encoding="utf-8"))
    assert [v["status"] for v in saved["videos"]] == ["partial", "error", "ok", "partial"]
    md = (request_dir / "report.md").read_text(encoding="utf-8")
    assert "download: ERROR: boom" in md and "frames: ffmpeg died" in md


def test_run_records_search_error_without_crashing(tmp_path, monkeypatch):
    def failing_search(query, n, lang):
        raise RuntimeError("search failed: ERROR: offline")

    monkeypatch.setattr(pipeline, "search", failing_search)
    report = pipeline.run("tema", out_dir=tmp_path)
    assert report["search_error"] == "search failed: ERROR: offline"
    assert report["videos"] == []
    md = (Path(report["request_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "Search error" in md
