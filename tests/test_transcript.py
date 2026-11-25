from findavideo.transcript import (
    apply_quality_rules, find_hits, normalize_text, parse_vtt, theme_terms,
)


def seg(start, end, text, nsp=0.1, lp=-0.3, cr=1.5):
    return {"start": start, "end": end, "text": text,
            "no_speech_prob": nsp, "avg_logprob": lp, "compression_ratio": cr}


def test_normalize_strips_accents_case_and_punctuation():
    assert normalize_text("  Quebra de SIGILO, Flávio! ") == "quebra de sigilo flavio"


def test_drops_probable_silence():
    # Values measured on the music-only test video.
    kept, dropped = apply_quality_rules([
        seg(0, 5, "1,2,3,4,5,6,7,8,9,10", nsp=0.60),
        seg(5, 10, "1,2,3,4,5,6,7,8,9,10", nsp=0.67),
        seg(10, 12, "fala real", nsp=0.5),
    ])
    assert [s["text"] for s in kept] == ["fala real"]
    assert len(dropped) == 2
    assert all(s["drop_reason"] == "no_speech_prob > 0.5" for s in dropped)


def test_flags_consecutive_repeats_on_every_occurrence():
    kept, _ = apply_quality_rules([
        seg(0, 1, "Obrigado."),
        seg(1, 2, "obrigado"),
        seg(2, 3, "Obrigado!"),
        seg(3, 4, "outra coisa"),
        seg(4, 5, "obrigado"),
    ])
    flags = [s["flags"] for s in kept]
    assert flags[0] == flags[1] == flags[2] == ["repeated"]
    assert flags[3] == [] and flags[4] == []


def test_flags_compression_and_logprob():
    kept, _ = apply_quality_rules([
        seg(0, 1, "a", cr=2.5),
        seg(1, 2, "b", lp=-1.2),
        seg(2, 3, "c", cr=2.4, lp=-1.0),
    ])
    assert kept[0]["flags"] == ["high_compression_ratio"]
    assert kept[1]["flags"] == ["low_avg_logprob"]
    assert kept[2]["flags"] == []


def test_subtitle_segments_without_scores_pass_unflagged():
    kept, dropped = apply_quality_rules([{"start": 0, "end": 1, "text": "oi"}])
    assert dropped == [] and kept[0]["flags"] == []


def test_theme_terms_drop_short_words_and_stopwords():
    assert theme_terms("Quebra de sigilo de Lula e Flávio") == ["quebra", "sigilo", "lula", "flavio"]


def test_find_hits_is_accent_and_case_insensitive_whole_word():
    segments = [
        seg(0, 4, "O TSE autorizou a QUEBRA do sigilo"),
        seg(4, 8, "Flavio comentou"),
        seg(8, 9, "sigilosamente nada"),
    ]
    hits = find_hits(segments, ["sigilo", "flávio"])
    assert [h["start"] for h in hits] == [0, 4]
    assert hits[0]["matched"] == ["sigilo"]
    assert hits[1]["matched"] == ["flavio"]


VTT = """WEBVTT
Kind: captions
Language: pt-BR

00:00:01.000 --> 00:00:03.500 align:start position:0%
Primeira linha
continua aqui

00:01:02.250 --> 00:01:04.000
<c>Segunda</c> fala

"""


def test_parse_vtt():
    assert parse_vtt(VTT) == [
        {"start": 1.0, "end": 3.5, "text": "Primeira linha continua aqui"},
        {"start": 62.25, "end": 64.0, "text": "Segunda fala"},
    ]
