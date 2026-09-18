import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.adapters.generic_manga import (
    _best_img_src,
    _chapter_number,
    _content,
    _slugify,
)
from app.adapters.manga import (
    MangaChapter,
    MangaChapterPages,
    MangaSeries,
    MangaSeriesManifest,
    MangaSourceAdapter,
)


class AsuraScansAdapter(MangaSourceAdapter):
    name = "asura-scans"

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "asurascans.com" or host.endswith(".asurascans.com")

    def extract(self, url: str, html: str, mode: str):
        raise NotImplementedError

    def extract_series_manifest(
        self,
        url: str,
        html: str,
    ) -> MangaSeriesManifest:
        tree = HTMLParser(html)

        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or "Untitled Series"
        )

        description = (
            _content(tree.css_first('meta[property="og:description"]'))
            or _content(tree.css_first('meta[name="description"]'))
        )

        cover_url = _content(tree.css_first('meta[property="og:image"]'))
        if cover_url:
            cover_url = urljoin(url, cover_url)
        else:
            # Asura currently serves covers from cdn.asurascans.com.
            for node in tree.css("img"):
                src = _best_img_src(node)
                alt = (node.attributes.get("alt") or "").strip()
                if src and alt and title.casefold() in alt.casefold():
                    cover_url = urljoin(url, src)
                    break

        body = tree.css_first("body")
        text = (
            " ".join(body.text(separator=" ", strip=True).split())
            if body
            else ""
        )
        lower = text.lower()

        if re.search(r"\bstatus\s+completed\b", lower):
            status = "completed"
        elif re.search(r"\bstatus\s+hiatus\b", lower):
            status = "hiatus"
        elif re.search(r"\bstatus\s+cancelled\b|\bstatus\s+canceled\b", lower):
            status = "cancelled"
        else:
            status = "ongoing"

        genres = []
        seen_genres = set()
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            label = " ".join(node.text(strip=True).split())
            if "genre" in href.lower() and label:
                key = label.casefold()
                if key not in seen_genres:
                    seen_genres.add(key)
                    genres.append(label)

        chapters = []
        seen_numbers = set()
        series_path = urlparse(url).path.rstrip("/")

        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            absolute = urljoin(url, href)
            parsed = urlparse(absolute)

            if not parsed.path.startswith(series_path + "/chapter/"):
                continue

            label = " ".join(node.text(separator=" ", strip=True).split())
            number = _chapter_number(label, absolute)

            if not number or number in seen_numbers:
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
                "Asura series page was fetched, but no chapter links were found."
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

    def extract_chapter_pages(
        self,
        url: str,
        html: str,
    ) -> MangaChapterPages:
        parsed_target = urlparse(url)

        # Asura series pages contain many CDN-hosted cover/recommendation
        # images. They are not reader pages. Reject them explicitly so 2B
        # cannot create a bogus editable chapter draft from a series URL.
        if "/chapter/" not in parsed_target.path.lower():
            raise ValueError(
                "This Asura URL is a series page, not a chapter page. "
                "Use a URL containing /chapter/<number> for 2B."
            )

        tree = HTMLParser(html)
        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first("title"))
            or "Asura Chapter"
        )

        number = _chapter_number(title, url) or "1"

        series_title = re.sub(
            r"\s+(?:chapter|ch\.?)\s+[0-9]+(?:\.[0-9]+)?.*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        pages = []
        seen = set()

        # Current Asura markup identifies reader images by Page N alt text
        # and serves them from its CDN. Both signals are used so UI images
        # are not imported as chapter pages.
        for node in tree.css("img"):
            src = _best_img_src(node)
            if not src:
                continue

            absolute = urljoin(url, src)
            parsed = urlparse(absolute)
            alt = (node.attributes.get("alt") or "").strip()

            is_page_alt = bool(
                re.search(r"\bpage\s+\d+\b", alt, flags=re.IGNORECASE)
            )
            is_asura_cdn = (
                parsed.hostname == "cdn.asurascans.com"
                or (parsed.hostname or "").endswith(".asurascans.com")
            )

            # Chapter reader images currently expose "Page N" alt text.
            # Requiring the page signal prevents covers, logos, and recommended
            # series images from being staged as chapter pages.
            if not (is_page_alt and is_asura_cdn):
                continue

            if absolute in seen:
                continue

            seen.add(absolute)
            pages.append((absolute, alt))

        def page_order(item):
            _url, alt = item
            match = re.search(r"\bpage\s+(\d+)\b", alt, flags=re.IGNORECASE)
            return int(match.group(1)) if match else 10**9

        pages.sort(key=page_order)
        urls = [value for value, _alt in pages]

        if not urls:
            raise ValueError(
                "Asura chapter page was fetched, but no reader images were found."
            )

        return MangaChapterPages(
            series=MangaSeries(
                title=series_title or title,
                slug=_slugify(series_title or title),
                description=None,
                cover_url=None,
            ),
            chapter=MangaChapter(
                title=title,
                slug=f"ch-{number.replace('.', '-')}",
                chapter_number=number,
                url=url,
            ),
            page_urls=urls,
        )
