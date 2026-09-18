from __future__ import annotations

import re
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.adapters.generic_manga import _chapter_number, _chapter_slug, _embedded_urls
from app.adapters.manga import MangaChapter
from app.fetcher import fetch_html

_SKIP_TOKENS = (
    "/login", "/signin", "/signup", "/account", "/profile", "/comment",
    "/privacy", "/terms", "/contact", "/search", "/tag/", "/genre/",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js",
    ".zip", ".pdf",
)


def _clean_url(value: str) -> str:
    clean, _fragment = urldefrag(value)
    return clean


def _same_series_query(series_url: str, candidate_url: str) -> bool:
    sq = parse_qs(urlparse(series_url).query)
    cq = parse_qs(urlparse(candidate_url).query)
    for key in ("titleId", "series", "seriesId", "mangaId", "id"):
        if key in sq and key in cq and sq[key] and cq[key] and sq[key][0] == cq[key][0]:
            return True
    return False


def extract_chapter_links(
    *,
    series_url: str,
    page_url: str,
    html: str,
    series_title: str,
) -> list[MangaChapter]:
    tree = HTMLParser(html)
    base_host = (urlparse(series_url).hostname or "").lower()
    series_path = urlparse(series_url).path.rstrip("/").lower()
    series_slug = series_path.split("/")[-1]
    title_tokens = [token for token in re.split(r"[^a-z0-9]+", series_title.lower()) if len(token) >= 4]

    found: list[MangaChapter] = []
    seen: set[str] = set()
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        absolute = _clean_url(urljoin(page_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != base_host:
            continue
        label = " ".join(node.text(separator=" ", strip=True).split())
        number = _chapter_number(label, absolute)
        if number is None:
            # Common query-based episode numbering, notably Naver-like sites.
            q = parse_qs(parsed.query)
            raw = (q.get("no") or q.get("chapter") or q.get("episode") or [None])[0]
            if raw and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(raw)):
                number = str(raw)
        if number is None:
            continue

        path = parsed.path.lower()
        relevance = (
            (series_path and path.startswith(series_path + "/"))
            or (series_slug and series_slug in path)
            or _same_series_query(series_url, absolute)
            or sum(token in (path + " " + label.lower()) for token in title_tokens) >= min(2, max(1, len(title_tokens)))
        )
        if not relevance:
            continue

        key = f"{number}:{absolute}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            MangaChapter(
                title=label or f"Chapter {number}",
                slug=_chapter_slug(absolute, number),
                chapter_number=number,
                url=absolute,
            )
        )

    # Hydration data can contain pagination/chapter URLs even when there are no
    # anchors yet. Apply exactly the same same-series guards as DOM links.
    for absolute in _embedded_urls(tree, page_url):
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() != base_host:
            continue
        number = _chapter_number("", absolute)
        if number is None:
            continue
        path = parsed.path.lower()
        relevance = (
            (series_path and path.startswith(series_path + "/"))
            or (series_slug and series_slug in path)
            or _same_series_query(series_url, absolute)
            or sum(token in path for token in title_tokens) >= min(2, max(1, len(title_tokens)))
        )
        if not relevance:
            continue
        key = f"{number}:{absolute}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            MangaChapter(
                title=f"Chapter {number}",
                slug=_chapter_slug(absolute, number),
                chapter_number=number,
                url=absolute,
            )
        )
    return found


def _crawl_priority(node, absolute: str) -> int:
    rel = (node.attributes.get("rel") or "").lower()
    label = " ".join(node.text(separator=" ", strip=True).lower().split())
    classes = (node.attributes.get("class") or "").lower()
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query)
    if "next" in rel or label in {"next", "older", ">", "›", "»"}:
        return 0
    if any(key in query for key in ("page", "paged", "p", "offset")):
        return 1
    if any(token in (label + " " + classes + " " + parsed.path.lower()) for token in ("page", "pagination", "chapter-list", "chapters", "episode-list")):
        return 2
    return 10


def internal_links(page_url: str, html: str, series_host: str) -> list[str]:
    tree = HTMLParser(html)
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    order = 0
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        absolute = _clean_url(urljoin(page_url, href))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.hostname or "").lower() != series_host:
            continue
        lower = absolute.lower()
        if any(token in lower for token in _SKIP_TOKENS):
            continue

        label = " ".join(node.text(separator=" ", strip=True).split())
        query = parse_qs(parsed.query)
        query_episode = (
            (query.get("no") or query.get("chapter") or query.get("episode") or [None])[0]
        )
        # Chapter/detail URLs are harvested by extract_chapter_links(). Do not
        # spend the bounded crawl budget downloading them while looking for
        # pagination/index pages that can reveal more chapters.
        if _chapter_number(label, absolute) is not None or (
            query_episode and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(query_episode))
        ):
            continue

        if absolute not in seen:
            seen.add(absolute)
            scored.append((_crawl_priority(node, absolute), order, absolute))
            order += 1
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored]


async def recursive_chapter_discovery(
    client: httpx.AsyncClient,
    *,
    series_url: str,
    first_html: str,
    series_title: str,
    max_depth: int,
    max_pages: int,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
) -> tuple[list[MangaChapter], dict]:
    max_depth = max(0, min(int(max_depth), 3))
    max_pages = max(1, min(int(max_pages), 50))
    host = (urlparse(series_url).hostname or "").lower()

    queue = deque([(series_url, 0, first_html)])
    visited: set[str] = set()
    chapters_by_number: dict[str, MangaChapter] = {}
    fetched = 0
    errors: list[str] = []

    while queue and fetched < max_pages:
        if cancel_check is not None:
            await cancel_check()
        page_url, depth, supplied_html = queue.popleft()
        page_url = _clean_url(page_url)
        if page_url in visited:
            continue
        visited.add(page_url)

        try:
            if supplied_html is None:
                result = await fetch_html(client, url=page_url)
                actual_url = result.final_url
                html = result.content.decode("utf-8", errors="replace")
            else:
                actual_url = page_url
                html = supplied_html
            fetched += 1
            if cancel_check is not None:
                await cancel_check()

            page_chapters = extract_chapter_links(
                series_url=series_url,
                page_url=actual_url,
                html=html,
                series_title=series_title,
            )
            page_links = internal_links(actual_url, html, host) if depth < max_depth else []

            if supplied_html is None and not page_chapters and not page_links:
                try:
                    rendered = await fetch_html(
                        client, url=actual_url, force_browser=True, browser_scroll=True
                    )
                    actual_url = rendered.final_url
                    html = rendered.content.decode("utf-8", errors="replace")
                    page_chapters = extract_chapter_links(
                        series_url=series_url, page_url=actual_url, html=html,
                        series_title=series_title,
                    )
                    page_links = internal_links(actual_url, html, host) if depth < max_depth else []
                except Exception as render_exc:
                    errors.append(f"{actual_url}: browser retry: {type(render_exc).__name__}: {render_exc}")

            for chapter in page_chapters:
                chapters_by_number.setdefault(chapter.chapter_number, chapter)

            if depth >= max_depth:
                continue
            for link in page_links:
                if link not in visited and all(item[0] != link for item in queue):
                    queue.append((link, depth + 1, None))
        except Exception as exc:
            # If the exception was the operation-wide cancellation signal,
            # re-check the durable flag outside the normal crawl-error path so
            # cancellation is never downgraded into a recoverable page error.
            if cancel_check is not None:
                await cancel_check()
            errors.append(f"{page_url}: {type(exc).__name__}: {exc}")

    chapters = sorted(chapters_by_number.values(), key=lambda chapter: float(chapter.chapter_number))
    return chapters, {
        "enabled": True,
        "max_depth": max_depth,
        "max_pages": max_pages,
        "pages_fetched": fetched,
        "visited": len(visited),
        "chapters_found": len(chapters),
        "errors": errors[-10:],
    }


def build_fallback_manifest(
    *,
    series_url: str,
    html: str,
    chapters: list[MangaChapter],
):
    from app.adapters.generic_manga import _best_img_src, _content, _slugify
    from app.adapters.manga import MangaSeries, MangaSeriesManifest

    tree = HTMLParser(html)
    title = (
        _content(tree.css_first("h1"))
        or _content(tree.css_first('meta[property="og:title"]'))
        or _content(tree.css_first("title"))
        or urlparse(series_url).path.rstrip("/").split("/")[-1].replace("-", " ").title()
    )
    description = (
        _content(tree.css_first('meta[name="description"]'))
        or _content(tree.css_first('meta[property="og:description"]'))
    )
    cover_url = _content(tree.css_first('meta[property="og:image"]'))
    if not cover_url:
        for selector in (".cover img", ".summary_image img", ".series-cover img", "[class*='cover'] img"):
            node = tree.css_first(selector)
            if node is not None:
                src = _best_img_src(node)
                if src:
                    cover_url = src
                    break
    if cover_url:
        cover_url = urljoin(series_url, cover_url)

    body = tree.css_first("body")
    lower = body.text(separator=" ", strip=True).lower() if body else ""
    if re.search(r"\bcompleted?\b|\bfinished\b", lower):
        status = "completed"
    elif "hiatus" in lower:
        status = "hiatus"
    elif "cancelled" in lower or "canceled" in lower:
        status = "cancelled"
    else:
        status = "ongoing"

    def labels(selectors: tuple[str, ...]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for selector in selectors:
            for node in tree.css(selector):
                label = " ".join(node.text(strip=True).split())
                key = label.casefold()
                if label and key not in seen:
                    seen.add(key)
                    values.append(label)
        return values

    return MangaSeriesManifest(
        series=MangaSeries(
            title=title,
            slug=_slugify(title),
            description=description,
            cover_url=cover_url,
            status=status,
        ),
        genres=labels((".genres a", ".genre a", "a[href*='genre']")),
        tags=labels((".tags a", ".tag a", "a[href*='tag']")),
        chapters=chapters,
    )
