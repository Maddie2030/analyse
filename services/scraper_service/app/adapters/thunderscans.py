import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.adapters.generic_manga import (
    GenericMangaAdapter,
    _best_img_src,
    _content,
    _slugify,
)
from app.adapters.manga import MangaChapter, MangaChapterPages, MangaSeries, MangaSeriesManifest


class ThunderScansAdapter(GenericMangaAdapter):
    name = "thunderscans"

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "en-thunderscans.com" or host.endswith(".en-thunderscans.com")

    def extract_series_manifest(self, url: str, html: str) -> MangaSeriesManifest:
        tree = HTMLParser(html)
        parsed = urlparse(url)
        series_slug = parsed.path.rstrip("/").split("/")[-1]

        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or _content(tree.css_first("title"))
            or series_slug.replace("-", " ").title()
        )
        description = (
            _content(tree.css_first('meta[name="description"]'))
            or _content(tree.css_first('meta[property="og:description"]'))
        )
        cover_url = _content(tree.css_first('meta[property="og:image"]'))
        if not cover_url:
            for selector in (".seriestuimg img", ".thumb img", "[class*='cover'] img"):
                node = tree.css_first(selector)
                if node is not None:
                    src = _best_img_src(node)
                    if src:
                        cover_url = src
                        break
        if cover_url:
            cover_url = urljoin(url, cover_url)

        body = tree.css_first("body")
        body_text = body.text(separator=" ", strip=True).lower() if body else ""
        if "status completed" in body_text or re.search(r"\bcompleted\b", body_text):
            status = "completed"
        elif "hiatus" in body_text:
            status = "hiatus"
        elif "cancelled" in body_text or "canceled" in body_text:
            status = "cancelled"
        else:
            status = "ongoing"

        genres: list[str] = []
        seen_genres: set[str] = set()
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            label = " ".join(node.text(strip=True).split())
            if not label:
                continue
            if "genre" in href.lower() or "/genres/" in href.lower():
                key = label.casefold()
                if key not in seen_genres:
                    seen_genres.add(key)
                    genres.append(label)

        chapters: list[MangaChapter] = []
        seen_numbers: set[str] = set()
        chapter_path_re = re.compile(
            rf"/{re.escape(series_slug)}-chapter-([0-9]+(?:\.[0-9]+)?)/?$",
            flags=re.IGNORECASE,
        )

        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            absolute = urljoin(url, href)
            ap = urlparse(absolute)
            if ap.hostname != parsed.hostname:
                continue

            label = " ".join(node.text(separator=" ", strip=True).split())
            match = chapter_path_re.search(ap.path)
            if match:
                number = match.group(1)
            else:
                text_match = re.search(
                    r"\bchapter\s+([0-9]+(?:\.[0-9]+)?)\b",
                    label,
                    flags=re.IGNORECASE,
                )
                if not text_match:
                    continue
                number = text_match.group(1)
                # Thunder chapter URLs are root-level; require title/series slug
                # relevance when matching by text to avoid recommendations.
                path_norm = ap.path.lower().replace("_", "-")
                if series_slug.lower() not in path_norm:
                    continue

            if number in seen_numbers:
                continue
            seen_numbers.add(number)
            chapters.append(
                MangaChapter(
                    title=label or f"Chapter {number}",
                    slug=f"ch-{number.replace('.', '-')}",
                    chapter_number=number,
                    url=absolute,
                )
            )

        chapters.sort(key=lambda chapter: float(chapter.chapter_number))
        if not chapters:
            raise ValueError(
                "ThunderScans page was fetched, but no accessible chapter links were found."
            )

        return MangaSeriesManifest(
            series=MangaSeries(
                title=title,
                slug=_slugify(title),
                description=description,
                cover_url=cover_url,
                status=status,
            ),
            genres=genres,
            tags=[],
            chapters=chapters,
        )
    def extract_chapter_pages(self, url: str, html: str) -> MangaChapterPages:
        """Extract Thunder's WordPress reader without paying for Chromium.

        Thunder uses common lazy-loaded reader containers. Prefer those
        containers and their data-* sources so navigation/cover/ad images never
        become staged pages. The generic adapter remains the compatibility
        fallback for theme changes.
        """
        tree = HTMLParser(html)
        nodes = []
        seen_nodes: set[int] = set()
        for selector in (
            ".reading-content .page-break img",
            ".reading-content img",
            "#readerarea img",
            ".chapter-content img",
            "[class*='chapter-content'] img",
            "[class*='reader'] img",
        ):
            for node in tree.css(selector):
                marker = id(node)
                if marker not in seen_nodes:
                    seen_nodes.add(marker)
                    nodes.append(node)

        pages: list[str] = []
        seen_urls: set[str] = set()
        for node in nodes:
            src = _best_img_src(node)
            if not src or src.startswith("data:"):
                continue
            absolute = urljoin(url, src)
            lower = absolute.lower()
            label = " ".join((node.attributes.get("alt") or "").lower().split())
            classes = (node.attributes.get("class") or "").lower()
            if any(token in f"{lower} {label} {classes}" for token in (
                "logo", "avatar", "icon", "emoji", "spinner", "banner",
                "advert", "placeholder",
            )):
                continue
            if absolute not in seen_urls:
                seen_urls.add(absolute)
                pages.append(absolute)

        if not pages:
            return super().extract_chapter_pages(url, html)

        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or _content(tree.css_first("title"))
            or "ThunderScans chapter"
        )
        match = re.search(r"-chapter-([0-9]+(?:\.[0-9]+)?)/?$", urlparse(url).path, re.I)
        if not match:
            match = re.search(r"\bchapter\s+([0-9]+(?:\.[0-9]+)?)", title, re.I)
        number = match.group(1) if match else "1"
        series_title = re.split(
            r"\bchapter\s+[0-9]+(?:\.[0-9]+)?", title, maxsplit=1, flags=re.I
        )[0].strip(" -|:") or title

        return MangaChapterPages(
            series=MangaSeries(
                title=series_title,
                slug=_slugify(series_title),
                description=None,
                cover_url=None,
            ),
            chapter=MangaChapter(
                title=title,
                slug=f"ch-{number.replace('.', '-')}",
                chapter_number=number,
                url=url,
            ),
            page_urls=pages,
        )

