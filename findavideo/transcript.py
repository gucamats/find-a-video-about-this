"""Transcribe a downloaded video and apply automatic quality checks."""

import html
import json
import re
import time
import unicodedata
from pathlib import Path

from . import tools

STOPWORDS = {
    # Portuguese
    "que", "para", "com", "uma", "uns", "umas", "dos", "das", "nos", "nas",
    "por", "pelo", "pela", "sobre", "como", "mais", "mas", "sem", "entre",
    # English
    "the", "and", "for", "with", "from", "about",
}


def normalize_text(text):
    """Lowercase, no accents, punctuation turned into spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", stripped.lower()).split())


def apply_quality_rules(segments, no_speech_max=0.5, compression_max=2.4,
                        logprob_min=-1.0):
    """Drop probable silence; flag suspicious segments. Returns (kept, dropped).

    Subtitle segments carry no scores and only go through the repeat check.
    """
    kept, dropped = [], []
    for segment in segments:
        s = dict(segment)
        nsp = s.get("no_speech_prob")
        if nsp is not None and nsp > no_speech_max:
            s["drop_reason"] = f"no_speech_prob > {no_speech_max}"
            dropped.append(s)
            continue
        flags = []
        if s.get("compression_ratio") is not None and s["compression_ratio"] > compression_max:
            flags.append("high_compression_ratio")
        if s.get("avg_logprob") is not None and s["avg_logprob"] < logprob_min:
            flags.append("low_avg_logprob")
        s["flags"] = flags
        kept.append(s)

    norms = [normalize_text(s["text"]) for s in kept]
    for i, norm in enumerate(norms):
        same_as_prev = i > 0 and norms[i - 1] == norm
        same_as_next = i + 1 < len(norms) and norms[i + 1] == norm
        if norm and (same_as_prev or same_as_next):
            kept[i]["flags"].insert(0, "repeated")
    return kept, dropped


def theme_terms(theme):
    """Keywords of a theme: words of 3+ letters that are not stopwords."""
    terms = []
    for word in normalize_text(theme).split():
        if len(word) >= 3 and word not in STOPWORDS and word not in terms:
            terms.append(word)
    return terms


def find_hits(segments, terms):
    """Segments whose text contains any term as a whole word or phrase."""
    norm_terms = [normalize_text(t) for t in terms if normalize_text(t)]
    hits = []
    for s in segments:
        padded = f" {normalize_text(s['text'])} "
        matched = [t for t in norm_terms if f" {t} " in padded]
        if matched:
            hits.append({"start": s["start"], "end": s["end"], "text": s["text"],
                         "matched": matched})
    return hits


def _vtt_time(value):
    parts = value.split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def parse_vtt(text):
    """Segments from a WebVTT subtitle file."""
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                start, end = line.split("-->")
                body = " ".join(lines[i + 1:])
                body = html.unescape(re.sub(r"<[^>]+>", "", body))
                body = " ".join(body.split())
                if body:
                    segments.append({"start": _vtt_time(start.strip()),
                                     "end": _vtt_time(end.strip().split()[0]),
                                     "text": body})
                break
    return segments


def youtube_subtitles(url, video_dir, sub_langs="pt-BR,pt", accept_language="pt-BR"):
    """Uploaded (not auto-generated) subtitles from YouTube. Raises if none."""
    langs = [lang.strip() for lang in sub_langs.split(",") if lang.strip()]
    base = Path(video_dir) / "subs"
    result = tools.run(tools.yt_dlp(
        "--skip-download", "--write-subs", "--sub-langs", ",".join(langs),
        "--sub-format", "vtt", "--no-playlist", "-o", str(base), "--", url,
        accept_language=accept_language,
    ))
    for lang in langs:
        path = Path(f"{base}.{lang}.vtt")
        if path.is_file():
            segments = parse_vtt(path.read_text(encoding="utf-8"))
            if segments:
                return lang, segments
    if result.returncode != 0:
        raise RuntimeError(tools.last_error(result.stderr))
    raise RuntimeError(f"no uploaded subtitles in {', '.join(langs)}")


def whisper_segments(video, model_size="small", language="pt"):
    """Local transcription on CPU. Returns (segments, timings)."""
    from faster_whisper import WhisperModel  # heavy import, only when needed

    t0 = time.monotonic()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    t1 = time.monotonic()
    raw, _info = model.transcribe(str(video), language=language)
    segments = [{
        "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
        "no_speech_prob": round(s.no_speech_prob, 3),
        "avg_logprob": round(s.avg_logprob, 3),
        "compression_ratio": round(s.compression_ratio, 3),
    } for s in raw]  # the generator does the actual work here
    t2 = time.monotonic()
    return segments, {"model_load_s": round(t1 - t0, 1), "transcribe_s": round(t2 - t1, 1)}


def transcribe(video_dir, model_size="small", language="pt", use_subtitles=True,
               sub_langs="pt-BR,pt", accept_language="pt-BR"):
    """Write `transcript.json` next to `video.mp4` and return its content.

    YouTube subtitles are a shortcut: any failure falls back to faster-whisper.
    """
    video_dir = Path(video_dir)
    video = video_dir / "video.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"{video} not found (run download first)")
    info_path = video_dir / "video.info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}

    data = {"video": str(video.resolve()), "language": language,
            "subtitle_error": None, "elapsed": {}}
    segments = None
    if use_subtitles and info.get("extractor_key") == "Youtube" and info.get("webpage_url"):
        t0 = time.monotonic()
        try:
            lang, segments = youtube_subtitles(info["webpage_url"], video_dir,
                                               sub_langs, accept_language)
            data.update({"source": "youtube-subtitles", "model": None,
                         "subtitle_language": lang})
        except Exception as exc:
            data["subtitle_error"] = str(exc)
        data["elapsed"]["subtitles_s"] = round(time.monotonic() - t0, 1)
    if segments is None:
        segments, timings = whisper_segments(video, model_size, language)
        data.update({"source": "faster-whisper", "model": model_size})
        data["elapsed"].update(timings)

    kept, dropped = apply_quality_rules(segments)
    data.update({
        "duration": tools.probe_duration(video),
        "rules": {"drop_if_no_speech_prob_above": 0.5,
                  "flag_if_compression_ratio_above": 2.4,
                  "flag_if_avg_logprob_below": -1.0,
                  "flag_consecutive_repeats": True},
        "counts": {"kept": len(kept), "dropped": len(dropped),
                   "flagged": sum(1 for s in kept if s["flags"])},
        "segments": kept,
        "dropped": dropped,
    })
    (video_dir / "transcript.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
