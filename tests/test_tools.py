from findavideo.tools import last_error, yt_dlp


def test_yt_dlp_sets_header_and_youtube_language_from_accept_language():
    cmd = yt_dlp("URL", "-j", accept_language="pt-BR")
    assert cmd[-2:] == ["URL", "-j"]
    assert "Accept-Language:pt-BR" in cmd
    # Without lang=pt, flat YouTube search returned English machine-translated titles.
    assert "youtube:lang=pt" in cmd


def test_yt_dlp_without_language_adds_nothing():
    assert yt_dlp("URL")[-1] == "URL"
    assert not any("lang" in part for part in yt_dlp("URL"))


def test_last_error_prefers_error_lines():
    stderr = "WARNING: a\nERROR: first\nERROR: second\ntrailing noise\n"
    assert last_error(stderr) == "ERROR: second"
    assert last_error("only warning\n") == "only warning"
    assert last_error("") == "unknown error (no output)"
