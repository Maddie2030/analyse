import re
from urllib.parse import parse_qs, urljoin, urlparse

from selectolax.parser import HTMLParser

from app.adapters.generic_manga import GenericMangaAdapter, _best_img_src, _content, _slugify
from app.adapters.manga import MangaChapter, MangaChapterPages, MangaSeries, MangaSeriesManifest


class NaverWebtoonAdapter(GenericMangaAdapter):
    name = "naver-webtoon"

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in {"comic.naver.com", "m.comic.naver.com"}

    @staticmethod
    def title_id(url: str) -> str | None:
        values = parse_qs(urlparse(url).query).get("titleId") or []
        return values[0] if values else None

    def extract_series_manifest(self, url: str, html: str) -> MangaSeriesManifest:
        tree = HTMLParser(html)
        title_id = self.title_id(url)
        if not title_id:
            raise ValueError("Naver Webtoon URL is missing titleId.")

        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first("h2"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or _content(tree.css_first("title"))
            or f"Naver Webtoon {title_id}"
        )
        title = re.sub(r"\s*::\s*네이버\s*웹툰\s*$", "", title, flags=re.IGNORECASE).strip()

        description = (
            _content(tree.css_first('meta[name="description"]'))
            or _content(tree.css_first('meta[property="og:description"]'))
        )
        cover_url = _content(tree.css_first('meta[property="og:image"]'))
        if not cover_url:
            for selector in (".detail_info img", ".thumb img", "[class*='Poster'] img"):
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
        status = "completed" if any(token in body_text for token in ("완결", "completed")) else "ongoing"

        chapters: list[MangaChapter] = []
        seen: set[str] = set()
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            absolute = urljoin(url, href)
            parsed = urlparse(absolute)
            if parsed.hostname not in {"comic.naver.com", "m.comic.naver.com"}:
                continue
            if "/webtoon/detail" not in parsed.path:
                continue
            query = parse_qs(parsed.query)
            if (query.get("titleId") or [None])[0] != title_id:
                continue
            number = (query.get("no") or [None])[0]
            if not number or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", number):
                continue

            # Avoid importing explicitly paid/locked entries as if public.
            label = " ".join(node.text(separator=" ", strip=True).split())
            parent_text = ""
            try:
                parent_text = " ".join(node.parent.text(separator=" ", strip=True).split()) if node.parent else ""
            except Exception:
                pass
            if "유료" in f"{label} {parent_text}":
                continue

            if number in seen:
                continue
            seen.add(number)
            chapters.append(
                MangaChapter(
                    title=label or f"Episode {number}",
                    slug=f"ch-{number.replace('.', '-')}",
                    chapter_number=number,
                    url=absolute,
                )
            )

        chapters.sort(key=lambda chapter: float(chapter.chapter_number))
        if not chapters:
            raise ValueError(
                "Naver Webtoon page was fetched, but no public episode links were found."
            )

        return MangaSeriesManifest(
            series=MangaSeries(
                title=title,
                slug=_slugify(title),
                description=description,
                cover_url=cover_url,
                status=status,
            ),
            genres=[],
            tags=[],
            chapters=chapters,
        )

    def extract_chapter_pages(self, url: str, html: str) -> MangaChapterPages:
        tree = HTMLParser(html)
        query = parse_qs(urlparse(url).query)
        number = (query.get("no") or [None])[0] or "1"
        raw_title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first("h2"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or _content(tree.css_first("title"))
            or f"Naver Episode {number}"
        )
        raw_title = re.sub(r"\s*::\s*네이버\s*웹툰\s*$", "", raw_title).strip()

        nodes = []
        seen_ids = set()
        for selector in (
            "#sectionContWide img",
            "#comic_view_area img",
            ".wt_viewer img",
            "[class*='viewer'] img",
            "article img",
            "main img",
        ):
            for node in tree.css(selector):
                marker = id(node)
                if marker not in seen_ids:
                    seen_ids.add(marker)
                    nodes.append(node)

        pages: list[str] = []
        seen_urls: set[str] = set()
        for node in nodes:
            src = _best_img_src(node)
            if not src:
                continue
            absolute = urljoin(url, src)
            lower = absolute.lower()
            if any(token in lower for token in ("logo", "banner", "thumb", "profile")):
                continue
            if absolute in seen_urls:
                continue
            seen_urls.add(absolute)
            pages.append(absolute)

        if not pages:
            raise ValueError(
                "Naver episode page was fetched, but no public reader images were found."
            )

        return MangaChapterPages(
            series=MangaSeries(
                title=raw_title,
                slug=_slugify(raw_title),
                description=None,
                cover_url=None,
            ),
            chapter=MangaChapter(
                title=raw_title,
                slug=f"ch-{number.replace('.', '-')}",
                chapter_number=number,
                url=url,
            ),
            page_urls=pages,
        )
