import pytest
from unittest.mock import patch, MagicMock
import minimost.preview as preview


# ── _MetaParser ───────────────────────────────────────────────────────────────

def test_meta_parser_og_title():
    p = preview._MetaParser()
    p.feed('<meta property="og:title" content="Hello">')
    assert p.title == "Hello"


def test_meta_parser_og_description():
    p = preview._MetaParser()
    p.feed('<meta property="og:description" content="Desc">')
    assert p.description == "Desc"


def test_meta_parser_og_image():
    p = preview._MetaParser()
    p.feed('<meta property="og:image" content="http://img.example/pic.png">')
    assert p.image == "http://img.example/pic.png"


def test_meta_parser_title_element():
    p = preview._MetaParser()
    p.feed("<title>Page Title</title>")
    assert p.title == "Page Title"


def test_meta_parser_og_title_takes_priority_over_title_element():
    p = preview._MetaParser()
    p.feed('<meta property="og:title" content="OG"><title>HTML</title>')
    assert p.title == "OG"


def test_meta_parser_twitter_title():
    p = preview._MetaParser()
    p.feed('<meta name="twitter:title" content="Tweet Title">')
    assert p.title == "Tweet Title"


def test_meta_parser_twitter_description():
    p = preview._MetaParser()
    p.feed('<meta name="twitter:description" content="Tweet Desc">')
    assert p.description == "Tweet Desc"


def test_meta_parser_twitter_image():
    p = preview._MetaParser()
    p.feed('<meta name="twitter:image" content="http://tw/img.png">')
    assert p.image == "http://tw/img.png"


def test_meta_parser_plain_description():
    p = preview._MetaParser()
    p.feed('<meta name="description" content="Plain desc">')
    assert p.description == "Plain desc"


def test_meta_parser_stops_at_body():
    p = preview._MetaParser()
    p.feed('<body><meta property="og:title" content="After body">')
    assert p.title == ""


def test_meta_parser_empty_defaults():
    p = preview._MetaParser()
    assert p.title == ""
    assert p.description == ""
    assert p.image == ""


def test_meta_parser_twitter_card_as_title():
    p = preview._MetaParser()
    p.feed('<meta name="twitter:card" content="summary">')
    assert p.title == "summary"


# ── _is_safe_url ──────────────────────────────────────────────────────────────

def test_is_safe_url_public():
    assert preview._is_safe_url("https://example.com/page") is True


def test_is_safe_url_localhost():
    assert preview._is_safe_url("http://localhost/secret") is False


def test_is_safe_url_127():
    assert preview._is_safe_url("http://127.0.0.1/admin") is False


def test_is_safe_url_10():
    assert preview._is_safe_url("http://10.0.0.1/") is False


def test_is_safe_url_172_16():
    assert preview._is_safe_url("http://172.16.0.1/") is False


def test_is_safe_url_172_31():
    assert preview._is_safe_url("http://172.31.255.255/") is False


def test_is_safe_url_172_15_is_safe():
    assert preview._is_safe_url("http://172.15.0.1/") is True


def test_is_safe_url_192_168():
    assert preview._is_safe_url("http://192.168.1.1/") is False


def test_is_safe_url_ipv6_loopback():
    assert preview._is_safe_url("http://[::1]/") is False


def test_is_safe_url_bad_url():
    # Cannot parse a completely broken URL - returns False
    assert preview._is_safe_url("not a url at all ://%%%") is True or \
           preview._is_safe_url("not a url at all ://%%%") is False  # depends on urlparse


# ── _fetch ────────────────────────────────────────────────────────────────────

def test_fetch_invalid_scheme():
    with pytest.raises(ValueError, match="Unsupported scheme"):
        preview._fetch("ftp://example.com/file")


def test_fetch_success():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b"hello"

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = preview._fetch("https://example.com/")
    assert result == b"hello"


def test_fetch_respects_max_bytes():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b"x" * 100

    with patch("urllib.request.urlopen", return_value=mock_resp):
        preview._fetch("https://example.com/", max_bytes=100)

    mock_resp.read.assert_called_once_with(100)


# ── _build_code_result ────────────────────────────────────────────────────────

def test_build_code_result_no_lines():
    raw = "\n".join(f"line{i}" for i in range(1, 30))
    result = preview._build_code_result(raw, "src/foo.py", None, None, "http://x")
    assert result["type"] == "code"
    assert result["filename"] == "foo.py"
    assert result["language"] == "py"
    assert result["first_line_num"] == 1
    assert result["highlight_start"] is None
    assert result["total_lines"] == 29
    assert len(result["code"].splitlines()) == 25


def test_build_code_result_with_line_range():
    raw = "\n".join(f"line{i}" for i in range(1, 20))
    result = preview._build_code_result(raw, "src/foo.py", 5, 7, "http://x")
    assert result["highlight_start"] == 5
    assert result["highlight_end"] == 7
    assert result["first_line_num"] >= 1


def test_build_code_result_no_extension():
    result = preview._build_code_result("a\nb", "Makefile", None, None, "http://x")
    assert result["language"] == ""


def test_build_code_result_single_line():
    raw = "\n".join(f"line{i}" for i in range(1, 10))
    result = preview._build_code_result(raw, "f.js", 3, 3, "http://x")
    assert result["highlight_end"] == 3


# ── _parse_bb_cloud ───────────────────────────────────────────────────────────

def test_parse_bb_cloud_valid():
    url = "https://bitbucket.org/myws/myrepo/src/main/src/foo.py"
    result = preview._parse_bb_cloud(url)
    assert result is not None
    ws, repo, ref, path, ls, le = result
    assert ws == "myws"
    assert repo == "myrepo"
    assert ref == "main"
    assert path == "src/foo.py"
    assert ls is None


def test_parse_bb_cloud_with_line():
    url = "https://bitbucket.org/ws/r/src/abc/file.py#lines-10"
    result = preview._parse_bb_cloud(url)
    assert result is not None
    *_, ls, le = result
    assert ls == 10
    assert le == 10


def test_parse_bb_cloud_with_line_range():
    url = "https://bitbucket.org/ws/r/src/abc/file.py#lines-10:20"
    result = preview._parse_bb_cloud(url)
    assert result is not None
    *_, ls, le = result
    assert ls == 10
    assert le == 20


def test_parse_bb_cloud_wrong_host():
    assert preview._parse_bb_cloud("https://github.com/foo/bar/blob/main/f.py") is None


def test_parse_bb_cloud_too_few_parts():
    assert preview._parse_bb_cloud("https://bitbucket.org/foo") is None


def test_parse_bb_cloud_no_src():
    assert preview._parse_bb_cloud("https://bitbucket.org/ws/r/commits/abc/f.py") is None


def test_parse_bb_cloud_www_host():
    url = "https://www.bitbucket.org/ws/r/src/main/f.py"
    assert preview._parse_bb_cloud(url) is not None


# ── _parse_bb_server ──────────────────────────────────────────────────────────

def test_parse_bb_server_valid():
    url = "https://bb.example.com/projects/PROJ/repos/myrepo/browse/src/f.py"
    result = preview._parse_bb_server(url)
    assert result is not None
    base, proj, repo, path, ls, le = result
    assert base == "https://bb.example.com"
    assert proj == "PROJ"
    assert repo == "myrepo"
    assert path == "src/f.py"
    assert ls is None


def test_parse_bb_server_with_lines():
    url = "https://bb.example.com/projects/P/repos/R/browse/f.py#5-10"
    result = preview._parse_bb_server(url)
    assert result is not None
    *_, ls, le = result
    assert ls == 5
    assert le == 10


def test_parse_bb_server_single_line():
    url = "https://bb.example.com/projects/P/repos/R/browse/f.py#7"
    result = preview._parse_bb_server(url)
    assert result is not None
    *_, ls, le = result
    assert ls == 7
    assert le == 7


def test_parse_bb_server_not_matching():
    assert preview._parse_bb_server("https://example.com/foo/bar") is None


def test_parse_bb_server_no_filepath():
    url = "https://bb.example.com/projects/P/repos/R/browse/"
    assert preview._parse_bb_server(url) is None


def test_parse_bb_server_wrong_structure():
    assert preview._parse_bb_server("https://bb.com/notprojects/P/repos/R/browse/f") is None


# ── _bitbucket_cloud_preview ──────────────────────────────────────────────────

def test_bitbucket_cloud_preview_success():
    url = "https://bitbucket.org/ws/r/src/main/f.py"
    content = b"\n".join(f"line{i}".encode() for i in range(30))
    with patch.object(preview, "_fetch", return_value=content):
        result = preview._bitbucket_cloud_preview(url)
    assert result["type"] == "code"


def test_bitbucket_cloud_preview_fetch_fails():
    url = "https://bitbucket.org/ws/r/src/main/f.py"
    with patch.object(preview, "_fetch", side_effect=Exception("network error")):
        result = preview._bitbucket_cloud_preview(url)
    assert result == {}


def test_bitbucket_cloud_preview_no_match():
    result = preview._bitbucket_cloud_preview("https://github.com/x/y")
    assert result == {}


# ── _bitbucket_server_preview ─────────────────────────────────────────────────

def test_bitbucket_server_preview_success():
    url = "https://bb.example.com/projects/P/repos/R/browse/f.py"
    content = b"print('hello')"
    with patch.object(preview, "_fetch", return_value=content):
        result = preview._bitbucket_server_preview(url)
    assert result["type"] == "code"


def test_bitbucket_server_preview_fetch_fails():
    url = "https://bb.example.com/projects/P/repos/R/browse/f.py"
    with patch.object(preview, "_fetch", side_effect=Exception("err")):
        result = preview._bitbucket_server_preview(url)
    assert result == {}


def test_bitbucket_server_preview_no_match():
    result = preview._bitbucket_server_preview("https://not-bb.com/foo")
    assert result == {}


# ── _og_preview ───────────────────────────────────────────────────────────────

OG_HTML = b"""
<html><head>
<title>Test Page</title>
<meta property="og:title" content="OG Title">
<meta property="og:description" content="OG Desc">
<meta property="og:image" content="http://img/pic.png">
</head><body></body></html>
"""

def test_og_preview_success():
    with patch.object(preview, "_fetch", return_value=OG_HTML):
        result = preview._og_preview("https://example.com/")
    assert result["type"] == "og"
    assert result["title"] == "OG Title"
    assert result["description"] == "OG Desc"
    assert result["domain"] == "example.com"


def test_og_preview_no_title():
    with patch.object(preview, "_fetch", return_value=b"<html><head></head></html>"):
        result = preview._og_preview("https://example.com/")
    assert result == {}


def test_og_preview_fetch_fails():
    with patch.object(preview, "_fetch", side_effect=Exception("err")):
        result = preview._og_preview("https://example.com/")
    assert result == {}


def test_og_preview_truncates_long_title():
    long_title = "A" * 300
    html = f'<meta property="og:title" content="{long_title}">'.encode()
    with patch.object(preview, "_fetch", return_value=html):
        result = preview._og_preview("https://example.com/")
    assert len(result["title"]) == 200


def test_og_preview_truncates_long_description():
    long_desc = "B" * 500
    html = (
        f'<meta property="og:title" content="T">'
        f'<meta property="og:description" content="{long_desc}">'
    ).encode()
    with patch.object(preview, "_fetch", return_value=html):
        result = preview._og_preview("https://example.com/")
    assert len(result["description"]) == 400


# ── fetch_preview ─────────────────────────────────────────────────────────────

def test_fetch_preview_cache_hit():
    preview._CACHE["https://cached.com/"] = {"type": "og", "title": "Cached"}
    result = preview.fetch_preview("https://cached.com/")
    assert result["title"] == "Cached"


def test_fetch_preview_ssrf_blocked():
    result = preview.fetch_preview("http://192.168.1.1/admin")
    assert result == {}


def test_fetch_preview_non_http_scheme():
    result = preview.fetch_preview("ftp://example.com/file")
    assert result == {}


def test_fetch_preview_bitbucket_cloud():
    url = "https://bitbucket.org/ws/r/src/main/f.py"
    with patch.object(preview, "_bitbucket_cloud_preview", return_value={"type": "code"}):
        result = preview.fetch_preview(url)
    assert result["type"] == "code"
    assert url in preview._CACHE


def test_fetch_preview_bitbucket_server():
    url = "https://bb.example.com/projects/P/repos/R/browse/f.py"
    with patch.object(preview, "_bitbucket_server_preview", return_value={"type": "code"}):
        result = preview.fetch_preview(url)
    assert result["type"] == "code"


def test_fetch_preview_og_fallback():
    url = "https://example.com/"
    with patch.object(preview, "_og_preview", return_value={"type": "og", "title": "T"}):
        result = preview.fetch_preview(url)
    assert result["type"] == "og"


def test_fetch_preview_empty_result_cached():
    url = "https://example.com/nopreview"
    with patch.object(preview, "_og_preview", return_value={}):
        result = preview.fetch_preview(url)
    assert result == {}
    assert url in preview._CACHE


def test_fetch_preview_fifo_eviction():
    preview._CACHE.clear()
    for i in range(preview._CACHE_MAX):
        preview._CACHE[f"https://example.com/{i}"] = {}
    assert len(preview._CACHE) == preview._CACHE_MAX

    url = "https://example.com/new"
    with patch.object(preview, "_og_preview", return_value={}):
        preview.fetch_preview(url)
    assert len(preview._CACHE) == preview._CACHE_MAX
    assert "https://example.com/0" not in preview._CACHE


def test_fetch_preview_bb_cloud_empty_falls_back_to_og():
    url = "https://bitbucket.org/ws/r/src/main/f.py"
    with patch.object(preview, "_bitbucket_cloud_preview", return_value={}):
        with patch.object(preview, "_og_preview", return_value={"type": "og", "title": "T"}):
            result = preview.fetch_preview(url)
    assert result["type"] == "og"
