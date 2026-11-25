from findavideo.frames import (
    cap_evenly, choose_mode, drawtext_escape, merge_cuts, mmss, parse_scdet,
    select_moments,
)

SCDET_STDERR = """
[Parsed_scdet_0 @ 000002437ca380c0] lavfi.scd.score: 26.546, lavfi.scd.time: 3
[Parsed_showinfo_1 @ 000002437ca385c0] n:   0 pts:  30720 pts_time:3       duration:   1024 fmt:yuv444p
[Parsed_showinfo_1 @ 000002437ca385c0] n:   1 pts:  41000 pts_time:4.0042  duration:   1024 fmt:yuv444p
frame=   50 fps=0.0 q=-0.0 Lsize=N/A time=00:00:04.90
"""


def test_mmss():
    assert mmss(0) == "00:00"
    assert mmss(65.9) == "01:05"
    assert mmss(3723) == "62:03"


def test_parse_scdet_reads_showinfo_pts_time():
    assert parse_scdet(SCDET_STDERR) == [3.0, 4.0042]


def test_merge_cuts_drops_cuts_closer_than_gap():
    assert merge_cuts([1.0, 1.2, 1.49, 1.6, 5.0, 3.0]) == [1.0, 1.6, 3.0, 5.0]
    assert merge_cuts([1.0, 1.4], min_gap=0.3) == [1.0, 1.4]


def test_choose_mode_news_like_uses_speech():
    # Measured on the 6 min news video: speech almost all along, 4 cuts.
    mode, reason = choose_mode(duration=374, speech_seconds=330, cuts=4, hits=3)
    assert mode == "speech"
    assert "coverage" in reason


def test_choose_mode_motion_like_uses_cuts():
    # Measured on the 36 s music-only video: nothing kept, 33 cuts.
    assert choose_mode(duration=36, speech_seconds=0, cuts=33, hits=0)[0] == "cuts"


def test_choose_mode_dense_cuts_with_hits_is_cuts_and_says_hits_are_kept():
    # Fast-edited news package that speaks the theme: one frame per cut,
    # and select_moments adds the theme-hit moments on top (tests below).
    mode, reason = choose_mode(duration=60, speech_seconds=50, cuts=30, hits=2)
    assert mode == "cuts"
    assert "theme hits" in reason and "included" in reason


def test_select_moments_dense_cuts_and_speech_hits_include_hit_moments():
    moments = select_moments("cuts", duration=60, cuts=[2.0, 4.0, 30.0, 50.0],
                             hit_ranges=[(20.0, 24.0)], max_frames=36, interval=2.0)
    assert {20.0, 22.0} <= set(moments)          # theme mentions
    assert {0.3, 2.3, 4.3, 30.3, 50.3} <= set(moments)  # cuts
    assert moments == sorted(moments)


def test_select_moments_interval_mode_also_includes_hit_moments():
    moments = select_moments("interval", duration=10, cuts=[], hit_ranges=[(5.5, 6.0)],
                             max_frames=20, interval=4.0)
    assert moments == [0.0, 4.0, 5.5, 8.0]


def test_select_moments_cap_keeps_hit_moments_first():
    cuts = [float(c) for c in range(1, 60)]  # 59 cuts, one per second
    moments = select_moments("cuts", duration=60, cuts=cuts,
                             hit_ranges=[(30.5, 33.0)], max_frames=6, interval=2.0)
    # Both hit samples survive; the 4 remaining slots go to cut frames.
    assert len(moments) == 6
    assert {30.5, 32.5} <= set(moments)


def test_choose_mode_without_hits_or_dense_cuts_is_interval():
    assert choose_mode(duration=300, speech_seconds=280, cuts=5, hits=0)[0] == "interval"
    assert choose_mode(duration=300, speech_seconds=280, cuts=0, hits=0)[0] == "interval"


def test_choose_mode_sparse_cuts_do_not_mean_motion():
    # Smoke run: a 48 s lyric video (sung words, 1 cut, no hits) got only
    # 2 frames when any cut chose `cuts`.
    assert choose_mode(duration=48, speech_seconds=48, cuts=1, hits=0)[0] == "interval"
    assert choose_mode(duration=36, speech_seconds=0, cuts=3, hits=0)[0] == "interval"


def test_choose_mode_little_speech_no_cuts_is_interval():
    assert choose_mode(duration=60, speech_seconds=3, cuts=0, hits=1)[0] == "interval"


def test_select_moments_cuts_mode_includes_opening_shot():
    moments = select_moments("cuts", duration=10, cuts=[2.0, 2.3, 6.0],
                             hit_ranges=[], max_frames=20)
    assert moments == [0.3, 2.3, 6.3]


def test_select_moments_speech_mode_samples_inside_hits_and_adds_cuts_there():
    moments = select_moments("speech", duration=100, cuts=[17.0, 50.0],
                             hit_ranges=[(10.0, 18.0), (40.0, 41.0)],
                             max_frames=20, interval=2.0)
    # 10..16 sampled every 2 s; the cut at 17 lands at 17.3, more than 1 s
    # from 16, so it stays; 40 sampled; the cut at 50 is outside every hit.
    assert moments == [10.0, 12.0, 14.0, 16.0, 17.3, 40.0]


def test_select_moments_drops_cut_frame_next_to_a_sample():
    moments = select_moments("speech", duration=100, cuts=[11.0],
                             hit_ranges=[(10.0, 13.0)], max_frames=20, interval=2.0)
    assert moments == [10.0, 12.0]


def test_select_moments_interval_mode_clamps_to_duration():
    assert select_moments("interval", duration=5, cuts=[], hit_ranges=[],
                          max_frames=20, interval=2.0) == [0.0, 2.0, 4.0]


def test_select_moments_respects_cap():
    moments = select_moments("interval", duration=1000, cuts=[], hit_ranges=[],
                             max_frames=9, interval=1.0)
    assert len(moments) == 9
    assert moments[0] == 0.0 and moments[-1] == 999.0


def test_cap_evenly_keeps_order_and_ends():
    assert cap_evenly([1, 2, 3, 4, 5], 3) == [1, 3, 5]
    assert cap_evenly([1, 2], 5) == [1, 2]
    assert cap_evenly([1, 2, 3], 1) == [1]


def test_drawtext_escape_quotes_and_escapes_colons():
    # Verified against ffmpeg 9.0.2: unquoted `C\:` fails to parse.
    assert drawtext_escape("C:/Windows/Fonts/arialbd.ttf") == "'C\\:/Windows/Fonts/arialbd.ttf'"
    assert drawtext_escape("C:\\Windows\\Fonts\\arialbd.ttf") == "'C\\:/Windows/Fonts/arialbd.ttf'"
    assert drawtext_escape("01:05") == "'01\\:05'"
