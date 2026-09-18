from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from fastapi import HTTPException

from app.adapters.generic_manga import _slugify
from app.adapters.manga import MangaChapter, MangaChapterPages, MangaSeries, MangaSeriesManifest
from app.fetcher import fetch_external


def is_atsu_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == "atsu.moe"


def is_naver_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {"comic.naver.com", "m.comic.naver.com"}


def naver_mobile_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme or "https", "m.comic.naver.com", parsed.path, parsed.params, parsed.query, ""))


def _json_number(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else None


def _first(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _cover_value(value) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("large", "medium", "small", "url", "image", "src"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


async def _fetch_json(
    client: httpx.AsyncClient,
    url: str,
    referer: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    result = await fetch_external(
        client,
        url=url,
        accept="application/json,text/plain,*/*",
        max_bytes=15 * 1024 * 1024,
        referer=referer,
        expected="json",
        extra_headers=extra_headers,
    )
    try:
        data = json.loads(result.content.decode("utf-8", errors="strict"))
    except Exception as exc:
        raise HTTPException(502, f"Source API returned invalid JSON: {type(exc).__name__}.") from exc
    if not isinstance(data, dict):
        raise HTTPException(502, "Source API returned an unexpected JSON shape.")
    return data



def _naver_title_id(url: str) -> str:
    values = parse_qs(urlparse(url).query).get("titleId") or []
    title_id = str(values[0]).strip() if values else ""
    if not re.fullmatch(r"[0-9]+", title_id):
        raise HTTPException(422, "Naver Webtoon URL must contain a numeric titleId.")
    return title_id


def _naver_api_headers() -> dict[str, str]:
    # Naver's own browser API requests are same-origin and Korean-localized.
    # Supplying the same harmless request metadata improves reliability without
    # needing Chromium or any challenge bypass.
    return {
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        "Origin": "https://comic.naver.com",
    }


def _naver_level_path(value: object) -> str:
    raw = str(value or "WEBTOON").strip()
    # Matches Naver's own level-code-to-path convention used by mature
    # extractors such as gallery-dl while staying conservative for unknowns.
    path = raw.lower().replace("_c", "C", 1)
    return path if re.fullmatch(r"[a-zA-Z0-9_-]+", path) else "webtoon"


def _naver_article_is_explicitly_locked(item: dict) -> bool:
    # Do not try to circumvent login/paid entries. Only skip when Naver
    # explicitly marks an episode paid/locked; absence of a field is not a
    # reason to hide an otherwise public chapter.
    for key in ("charge", "paid", "isPaid", "isCharge", "locked", "isLocked"):
        if item.get(key) is True:
            return True
    if "free" in item and item.get("free") is False:
        return True
    code = str(_first(item.get("serviceStatus"), item.get("status"), "")).upper()
    return code in {"PAID", "LOCKED", "PURCHASE_REQUIRED"}


async def discover_naver_manifest(client: httpx.AsyncClient, url: str) -> MangaSeriesManifest:
    """Discover Naver series through its public JSON data plane.

    Naver's desktop list page is a client-rendered shell, so repeatedly
    launching Chromium just to discover episode links wastes CPU/RAM and is
    less stable than the same JSON endpoint used by the page itself.
    """
    title_id = _naver_title_id(url)
    base = "https://comic.naver.com"
    referer = f"{base}/webtoon/list?titleId={title_id}"

    try:
        info = await _fetch_json(
            client,
            f"{base}/api/article/list/info?titleId={title_id}",
            referer=referer,
            extra_headers=_naver_api_headers(),
        )
    except HTTPException:
        info = {}

    chapters: list[MangaChapter] = []
    seen: set[str] = set()
    page = 1
    level_code: object = _first(info.get("webtoonLevelCode"), "WEBTOON")
    first_list: dict | None = None

    # Hard bound protects against a malformed nextPage loop. 200 pages is
    # already far beyond normal Naver episode pagination.
    for _ in range(200):
        data = await _fetch_json(
            client,
            f"{base}/api/article/list?{urlencode({'titleId': title_id, 'page': page, 'sort': 'ASC'})}",
            referer=referer,
            extra_headers=_naver_api_headers(),
        )
        if first_list is None:
            first_list = data
        level_code = _first(data.get("webtoonLevelCode"), level_code)
        article_list = data.get("articleList")
        if not isinstance(article_list, list):
            article_list = []

        level_path = _naver_level_path(level_code)
        for item in article_list:
            if not isinstance(item, dict) or _naver_article_is_explicitly_locked(item):
                continue
            number = _json_number(_first(item.get("no"), item.get("episodeNo"), item.get("articleNo")))
            if not number or number in seen:
                continue
            seen.add(number)
            subtitle = str(_first(item.get("subtitle"), item.get("title"), f"Episode {number}"))
            chapter_url = f"{base}/{level_path}/detail?{urlencode({'titleId': title_id, 'no': number})}"
            chapters.append(
                MangaChapter(
                    title=subtitle,
                    slug=f"ch-{number.replace('.', '-')}",
                    chapter_number=number,
                    url=chapter_url,
                )
            )

        page_info = data.get("pageInfo") if isinstance(data.get("pageInfo"), dict) else {}
        next_page = page_info.get("nextPage")
        try:
            next_page_int = int(next_page) if next_page not in (None, "", False) else 0
        except (TypeError, ValueError):
            next_page_int = 0
        if not next_page_int or next_page_int == page:
            break
        page = next_page_int

    if not chapters:
        raise HTTPException(422, "Naver public episode API returned no accessible chapters.")

    merged = {}
    if isinstance(first_list, dict):
        merged.update(first_list)
    merged.update(info)

    title = str(_first(
        merged.get("titleName"), merged.get("webtoonTitle"), merged.get("title"),
        f"Naver Webtoon {title_id}",
    ))
    description = _first(
        merged.get("synopsis"), merged.get("description"), merged.get("summary"),
    )
    cover_url = _cover_value(_first(
        merged.get("thumbnailUrl"), merged.get("thumbnail"), merged.get("poster"), merged.get("image"),
    ))
    if cover_url:
        cover_url = urljoin(base, cover_url)

    finished = _first(merged.get("finished"), merged.get("isFinished"), merged.get("completed"))
    raw_status = str(_first(merged.get("status"), merged.get("webtoonStatus"), "")).lower()
    status = "completed" if finished is True or any(x in raw_status for x in ("complete", "finish", "end")) else "ongoing"

    genres: list[str] = []
    raw_genres = _first(merged.get("genres"), merged.get("genre"), merged.get("webtoonGenre"), [])
    if isinstance(raw_genres, str):
        raw_genres = [raw_genres]
    if isinstance(raw_genres, list):
        for item in raw_genres:
            label = str(_first(item.get("name"), item.get("title"), "") if isinstance(item, dict) else item).strip()
            if label and label not in genres:
                genres.append(label)

    chapters.sort(key=lambda chapter: float(chapter.chapter_number))
    return MangaSeriesManifest(
        series=MangaSeries(
            title=title,
            slug=_slugify(title),
            description=str(description) if description else None,
            cover_url=cover_url,
            status=status,
        ),
        genres=genres,
        tags=[],
        chapters=chapters,
    )

def _atsu_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"manga", "read"}:
        return parts[1]
    raise HTTPException(422, "Atsu URL must contain /manga/<id> or /read/<mangaId>/<chapterId>.")


async def discover_atsu_manifest(client: httpx.AsyncClient, url: str) -> MangaSeriesManifest:
    manga_id = _atsu_id(url)
    base = "https://atsu.moe"
    referer = f"{base}/manga/{manga_id}"

    page_data = await _fetch_json(client, f"{base}/api/manga/page?id={manga_id}", referer=referer)

    try:
        chapters_data = await _fetch_json(
            client,
            f"{base}/api/manga/allChapters?mangaId={manga_id}",
            referer=referer,
        )
    except HTTPException:
        chapters_data = {}

    try:
        info_data = await _fetch_json(
            client,
            f"{base}/api/manga/info?mangaId={manga_id}",
            referer=referer,
        )
    except HTTPException:
        info_data = {}

    page = page_data.get("mangaPage") if isinstance(page_data.get("mangaPage"), dict) else page_data
    info = info_data.get("manga") if isinstance(info_data.get("manga"), dict) else info_data

    title = _first(
        page.get("title") if isinstance(page, dict) else None,
        page.get("englishTitle") if isinstance(page, dict) else None,
        info.get("title") if isinstance(info, dict) else None,
        info.get("englishTitle") if isinstance(info, dict) else None,
    ) or f"Atsu {manga_id}"

    description = _first(
        page.get("description") if isinstance(page, dict) else None,
        page.get("synopsis") if isinstance(page, dict) else None,
        info.get("description") if isinstance(info, dict) else None,
        info.get("synopsis") if isinstance(info, dict) else None,
    )
    cover_url = _cover_value(
        _first(
            page.get("poster") if isinstance(page, dict) else None,
            page.get("posterMedium") if isinstance(page, dict) else None,
            info.get("poster") if isinstance(info, dict) else None,
            info.get("posterMedium") if isinstance(info, dict) else None,
        )
    )
    if cover_url:
        cover_url = urljoin(base, cover_url)

    raw_status = str(
        _first(
            page.get("status") if isinstance(page, dict) else None,
            info.get("status") if isinstance(info, dict) else None,
            "ongoing",
        )
    ).lower()
    status = "completed" if any(token in raw_status for token in ("complete", "finished")) else "ongoing"

    genres: list[str] = []
    raw_genres = _first(
        page.get("genres") if isinstance(page, dict) else None,
        info.get("genres") if isinstance(info, dict) else None,
        [],
    )
    if isinstance(raw_genres, list):
        for item in raw_genres:
            if isinstance(item, str):
                label = item.strip()
            elif isinstance(item, dict):
                label = str(_first(item.get("name"), item.get("title"), "")).strip()
            else:
                label = ""
            if label and label not in genres:
                genres.append(label)

    raw_chapters = chapters_data.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raw_chapters = info_data.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raw_chapters = page_data.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raw_chapters = page.get("chapters") if isinstance(page, dict) else None
    if not isinstance(raw_chapters, list):
        raw_chapters = []

    chapters: list[MangaChapter] = []
    seen_numbers: set[str] = set()
    for index, item in enumerate(raw_chapters, start=1):
        if not isinstance(item, dict):
            continue
        chapter_id = _first(item.get("id"), item.get("chapterId"), item.get("chapter_id"))
        if not chapter_id:
            continue
        title_value = str(_first(item.get("title"), item.get("name"), f"Chapter {index}"))
        number = _first(
            _json_number(item.get("number")),
            _json_number(item.get("chapterNumber")),
            _json_number(item.get("chapter")),
            _json_number(title_value),
        )
        if not number or number in seen_numbers:
            continue
        seen_numbers.add(number)
        chapters.append(
            MangaChapter(
                title=title_value,
                slug=f"ch-{number.replace('.', '-')}",
                chapter_number=number,
                url=f"{base}/read/{manga_id}/{chapter_id}",
            )
        )

    chapters.sort(key=lambda chapter: float(chapter.chapter_number))
    if not chapters:
        raise HTTPException(422, "Atsu API returned manga metadata but no usable numeric chapters.")

    return MangaSeriesManifest(
        series=MangaSeries(
            title=str(title),
            slug=_slugify(str(title)),
            description=str(description) if description else None,
            cover_url=cover_url,
            status=status,
        ),
        genres=genres,
        tags=[],
        chapters=chapters,
    )


def _normalize_atsu_image(url: str, base: str = "https://atsu.moe") -> str:
    value = url.strip()
    # Some historical Atsu API records were observed with malformed concatenated
    # host+scheme strings. Repair only that obvious serialization defect.
    for prefix in ("https://atsu.moehttps://", "http://atsu.moehttps://", "atsu.moehttps://"):
        if value.startswith(prefix):
            value = "https://" + value.split("https://", 1)[1]
            break
    return urljoin(base, value)


async def fetch_atsu_chapter_pages(client: httpx.AsyncClient, url: str) -> MangaChapterPages:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "read":
        raise HTTPException(422, "Atsu chapter URL must contain /read/<mangaId>/<chapterId>.")
    manga_id, chapter_id = parts[1], parts[2]
    endpoint = f"https://atsu.moe/api/read/chapter?{urlencode({'mangaId': manga_id, 'chapterId': chapter_id})}"
    data = await _fetch_json(client, endpoint, referer=url)
    chapter_data = data.get("readChapter") if isinstance(data.get("readChapter"), dict) else data
    raw_pages = chapter_data.get("pages") if isinstance(chapter_data, dict) else None
    if not isinstance(raw_pages, list):
        raw_pages = []

    pages: list[str] = []
    seen: set[str] = set()
    for item in raw_pages:
        if isinstance(item, str):
            image = item
        elif isinstance(item, dict):
            image = _first(item.get("image"), item.get("url"), item.get("src"))
        else:
            image = None
        if not image:
            continue
        absolute = _normalize_atsu_image(str(image))
        if absolute not in seen:
            seen.add(absolute)
            pages.append(absolute)

    if not pages:
        raise HTTPException(422, "Atsu chapter API returned no page images.")

    title = str(_first(chapter_data.get("title") if isinstance(chapter_data, dict) else None, "Atsu Chapter"))
    number = _json_number(title) or "1"
    return MangaChapterPages(
        series=MangaSeries(title=title, slug=_slugify(title), description=None, cover_url=None),
        chapter=MangaChapter(
            title=title,
            slug=f"ch-{number.replace('.', '-')}",
            chapter_number=number,
            url=url,
        ),
        page_urls=pages,
    )
