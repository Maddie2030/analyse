from fastapi import HTTPException
from selectolax.parser import HTMLParser

from app.adapters.generic_manga import GenericMangaAdapter, _best_img_src
from app.adapters.naver import NaverWebtoonAdapter
from app.adapters.thunderscans import ThunderScansAdapter
from app.fetcher import browser_headers, _looks_like_js_shell, _validate_payload


def test_rejects_html_mislabeled_as_image():
    try:
        _validate_payload(
            content=b"<!doctype html><html><body>Access denied</body></html>",
            content_type="image/webp",
            expected="image",
            max_bytes=1024 * 1024,
        )
    except HTTPException:
        pass
    else:
        raise AssertionError("mislabeled HTML must not be accepted as an image")


def test_accepts_avif_by_signature():
    body = b"\x00\x00\x00\x18ftypavif" + b"x" * 32
    assert _validate_payload(
        content=body,
        content_type="application/octet-stream",
        expected="image",
        max_bytes=1024,
    ) == "image/avif"


def test_js_shell_detection_is_conservative():
    assert _looks_like_js_shell(b'<html><body><div id="__next"></div><script src="/_next/static/x.js"></script></body></html>')
    rich = b'<html><body><div id="__next">' + (b'<a href="/x">Chapter</a>' * 10) + b'</div></body></html>'
    assert not _looks_like_js_shell(rich)


def test_background_image_candidate():
    tree = HTMLParser('<div data-bg="https://cdn.example/page.webp"></div>')
    assert _best_img_src(tree.css_first('[data-bg]')) == "https://cdn.example/page.webp"


def test_noscript_chapter_images_are_discovered():
    html = '''<html><head><title>Demo Chapter 12</title></head><body>
    <main><noscript>&lt;img src="https://cdn.example/001.webp" /&gt;</noscript></main>
    </body></html>'''
    result = GenericMangaAdapter().extract_chapter_pages("https://example.com/demo-chapter-12/", html)
    assert result.page_urls == ["https://cdn.example/001.webp"]


def test_source_specific_headers_can_override_locale_without_transport_headers():
    headers = browser_headers(
        accept="application/json",
        referer="https://comic.naver.com/webtoon/list?titleId=844505",
        extra_headers={
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Origin": "https://comic.naver.com",
            "Host": "evil.invalid",
        },
    )
    assert headers["Accept-Language"].startswith("ko-KR")
    assert headers["Origin"] == "https://comic.naver.com"
    assert "Host" not in headers


def test_thunderscans_static_lazy_reader_pages_are_discovered():
    html = """<html><head><title>Leu Leu Leu Chapter 27</title></head><body>
    <div class="reading-content">
      <div class="page-break"><img src="/placeholder.gif" data-src="https://cdn.example/001.webp"></div>
      <div class="page-break"><img data-lazy-src="https://cdn.example/002.webp"></div>
    </div></body></html>"""
    result = ThunderScansAdapter().extract_chapter_pages(
        "https://en-thunderscans.com/leu-leu-leu-chapter-27/", html
    )
    assert result.chapter.chapter_number == "27"
    assert result.page_urls == [
        "https://cdn.example/001.webp",
        "https://cdn.example/002.webp",
    ]


def test_naver_static_reader_area_pages_are_discovered():
    html = """<html><head><title>Sample Chapter :: 네이버 웹툰</title></head><body>
    <div id="comic_view_area">
      <img src="https://image-comic.pstatic.net/001.jpg">
      <img src="https://image-comic.pstatic.net/002.jpg">
    </div></body></html>"""
    result = NaverWebtoonAdapter().extract_chapter_pages(
        "https://comic.naver.com/webtoon/detail?titleId=844505&no=7", html
    )
    assert result.chapter.chapter_number == "7"
    assert len(result.page_urls) == 2


def test_json_gate_is_rejected_before_parser_boundary():
    try:
        _validate_payload(
            content=b"<!doctype html><html><body>verify you are human</body></html>",
            content_type="text/html",
            expected="json",
            max_bytes=1024 * 1024,
        )
    except HTTPException as exc:
        assert exc.status_code == 502
    else:
        raise AssertionError("HTML returned by a JSON API must trigger transport escalation")


def test_json_payload_accepts_plain_text_mime_when_body_is_json():
    assert _validate_payload(
        content=b'{"articleList":[]}',
        content_type="text/plain",
        expected="json",
        max_bytes=1024,
    ) == "text/plain"
