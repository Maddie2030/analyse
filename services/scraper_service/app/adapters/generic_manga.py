import html as html_lib
import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.chapter_identity import chapter_slug_from_number

from app.adapters.manga import (
    MangaChapter,
    MangaChapterPages,
    MangaSeries,
    MangaSeriesManifest,
    MangaSourceAdapter,
)


_IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-original-src",
    "data-cfsrc",
    "data-url",
    "data-image",
    "data-lazy",
    "data-bg",
    "data-background",
    "data-background-image",
)

_SCRIPT_STRING_URL_RE = re.compile(
    r"[\"'`]((?:https?:)?(?:\\?/\\?/)[^\"'`<>\s]+|\\?/(?:[^\"'`<>\s])+)[\"'`]",
    flags=re.IGNORECASE,
)
_JSON_URL_VALUE_RE = re.compile(
    r"[\"'](?:src|url|image|imageurl|pageurl|original|datasrc|data-src)[\"']\s*:\s*[\"']([^\"']+)[\"']",
    flags=re.IGNORECASE,
)
_IMAGE_URL_RE = re.compile(
    r"\.(?:jpe?g|png|webp|gif|avif|bmp)(?:$|[?#])",
    flags=re.IGNORECASE,
)


def _normalize_embedded_url(base_url: str, value: str) -> str | None:
    candidate = html_lib.unescape(value).strip().strip("\"'`")
    candidate = (
        candidate.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u003A", ":")
        .replace("\\u003a", ":")
    )
    if candidate.startswith("//"):
        candidate = f"{urlparse(base_url).scheme or 'https'}:{candidate}"
    absolute = urljoin(base_url, candidate)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return absolute


def _embedded_urls(tree: HTMLParser, base_url: str) -> list[str]:
    # Recover URLs serialized in Next.js/Nuxt/SPA JSON before paying the cost
    # of a real browser render.
    found: list[str] = []
    seen: set[str] = set()
    for node in tree.css("script"):
        try:
            text = node.text(separator=" ", strip=False) or ""
        except Exception:
            text = ""
        if not text:
            continue
        values = [m.group(1) for m in _SCRIPT_STRING_URL_RE.finditer(text)]
        values.extend(m.group(1) for m in _JSON_URL_VALUE_RE.finditer(text))
        for raw in values:
            absolute = _normalize_embedded_url(base_url, raw)
            if absolute and absolute not in seen:
                seen.add(absolute)
                found.append(absolute)
    return found


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "untitled"


def _content(node) -> str | None:
    if node is None:
        return None
    return (
        node.attributes.get("content")
        or node.text(strip=True)
        or None
    )


def _chapter_number(text: str, url: str) -> str | None:
    patterns = [
        r"(?:chapter|chap|ch\.?|episode|ep\.?)\s*[-_:]?\s*([0-9]+(?:\.[0-9]+)?)",
        r"/chapter/(?:chapter[-_])?([0-9]+(?:\.[0-9]+)?)(?:/|$|\?)",
        r"/chapter[-_]([0-9]+(?:\.[0-9]+)?)(?:/|$|\?)",
        r"/ch-?([0-9]+(?:\.[0-9]+)?)(?:/|$|\?)",
        r"/episode[-_/]([0-9]+(?:\.[0-9]+)?)(?:/|$|\?)",
    ]

    for value in (text, url):
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                return match.group(1)

    return None


def _chapter_slug(url: str, number: str) -> str:
    # Chapter identity is intentionally independent of source URL/title.
    # Keep the URL argument for adapter compatibility, but derive the slug only
    # from the canonical chapter number.
    _ = url
    return chapter_slug_from_number(number)


def _is_placeholder_image_value(value: str | None) -> bool:
    if not value:
        return True
    raw = html_lib.unescape(str(value)).strip().strip('"\'')
    lower = raw.lower()
    if not raw or lower.startswith(("data:", "blob:", "javascript:")):
        return True
    placeholder_tokens = (
        "transparent.gif", "spacer.gif", "blank.gif", "pixel.gif",
        "placeholder", "lazy-placeholder", "loading.svg", "loading.gif",
        "data:image/", "about:blank",
    )
    return any(token in lower for token in placeholder_tokens)


def _best_img_src(node) -> str | None:
    def best_srcset(value: str | None) -> str | None:
        if not value:
            return None
        items = []
        for raw in value.split(","):
            parts = raw.strip().split()
            if not parts or _is_placeholder_image_value(parts[0]):
                continue
            score = 0
            if len(parts) > 1:
                descriptor = parts[-1].lower()
                try:
                    if descriptor.endswith("w"):
                        score = int(descriptor[:-1])
                    elif descriptor.endswith("x"):
                        score = int(float(descriptor[:-1]) * 1000)
                except ValueError:
                    pass
            items.append((score, parts[0]))
        return sorted(items)[-1][1] if items else None

    # Lazy-loading plugins commonly leave a transparent/placeholder `src`
    # while the real asset is held in data-src/data-lazy-src. Prefer explicit
    # lazy/original attributes first, and only use normal src/srcset last.
    for attr in (
        "data-srcset", "data-lazy-srcset", "data-original-srcset",
    ):
        candidate = best_srcset(node.attributes.get(attr))
        if candidate:
            return candidate

    for attr in (
        "data-src", "data-lazy-src", "data-original", "data-original-src",
        "data-cfsrc", "data-url", "data-image", "data-lazy", "data-bg",
        "data-background", "data-background-image",
    ):
        value = node.attributes.get(attr)
        if value and not _is_placeholder_image_value(value):
            return value

    candidate = best_srcset(node.attributes.get("srcset"))
    if candidate:
        return candidate

    src = node.attributes.get("src")
    if src and not _is_placeholder_image_value(src):
        return src

    style = node.attributes.get("style") or ""
    match = re.search(r'(?:background(?:-image)?|content)\s*:\s*url\((?:[\'"])?([^)\'"]+)', style, flags=re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        if not _is_placeholder_image_value(value):
            return value

    return None


class GenericMangaAdapter(MangaSourceAdapter):
    name = "generic-manga"

    def matches(self, url: str) -> bool:
        return True

    def extract(self, url: str, html: str, mode: str):
        raise NotImplementedError

    def extract_series_manifest(
        self,
        url: str,
        html: str,
    ) -> MangaSeriesManifest:
        tree = HTMLParser(html)
        parsed_series = urlparse(url)
        series_path = parsed_series.path.rstrip("/")

        title = (
            _content(tree.css_first("h1"))
            or _content(tree.css_first('meta[property="og:title"]'))
            or _content(tree.css_first("title"))
            or "Untitled Series"
        )

        description = (
            _content(tree.css_first('meta[name="description"]'))
            or _content(tree.css_first('meta[property="og:description"]'))
        )

        cover_url = _content(
            tree.css_first('meta[property="og:image"]')
        )
        if not cover_url:
            cover_node = (
                tree.css_first(".cover img")
                or tree.css_first(".summary_image img")
                or tree.css_first(".series-cover img")
                or tree.css_first("[class*='cover'] img")
            )
            if cover_node is not None:
                cover_url = _best_img_src(cover_node)

        if cover_url:
            cover_url = urljoin(url, cover_url)

        body = tree.css_first("body")
        body_text = (
            body.text(separator=" ", strip=True).lower()
            if body
            else ""
        )

        if re.search(r"\bcompleted?\b|\bfinished\b", body_text):
            status = "completed"
        elif "hiatus" in body_text:
            status = "hiatus"
        elif "cancelled" in body_text or "canceled" in body_text:
            status = "cancelled"
        else:
            status = "ongoing"

        def collect_labels(selectors: list[str]) -> list[str]:
            seen: set[str] = set()
            values: list[str] = []

            for selector in selectors:
                for node in tree.css(selector):
                    text = " ".join(node.text(strip=True).split())
                    if not text:
                        continue
                    key = text.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    values.append(text)

            return values

        genres = collect_labels([
            ".genres a",
            ".genre a",
            ".genres-content a",
            "[class*='genre'] a",
            "a[href*='genre']",
        ])

        tags = collect_labels([
            ".tags a",
            ".tag a",
            ".tags-content a",
            "[class*='tag'] a",
            "a[href*='tag']",
        ])

        chapter_candidates = []
        seen_urls: set[str] = set()

        # Harvest broadly like scraper_v_1.0.3 instead of trusting one theme.
        for node in tree.css("a[href], [data-href], [data-url], [data-chapter-url], [data-link]"):
            href = (
                node.attributes.get("href")
                or node.attributes.get("data-href")
                or node.attributes.get("data-url")
                or node.attributes.get("data-chapter-url")
                or node.attributes.get("data-link")
            )
            if not href:
                continue

            absolute = urljoin(url, href)
            parsed = urlparse(absolute)
            text = " ".join(node.text(separator=" ", strip=True).split())

            if parsed.scheme not in {"http", "https"}:
                continue

            if parsed.hostname != parsed_series.hostname:
                continue

            number = _chapter_number(text, absolute)
            if not number:
                continue

            # Keep the old protection against unrelated recommendation links,
            # but also support sites whose chapter URLs live at the site root
            # (for example /series-slug-chapter-35/).
            series_slug = series_path.split("/")[-1].lower() if series_path else ""
            path_lower = parsed.path.lower().replace("_", "-")
            under_series_path = bool(
                series_path and parsed.path.startswith(series_path + "/")
            )
            root_slug_match = bool(series_slug and series_slug in path_lower)
            if series_path and not (under_series_path or root_slug_match):
                continue

            if absolute in seen_urls:
                continue

            seen_urls.add(absolute)
            chapter_candidates.append(
                MangaChapter(
                    title=text or None,
                    slug=_chapter_slug(absolute, number),
                    chapter_number=number,
                    url=absolute,
                )
            )

        # Some SPA themes serialize chapter URLs but do not emit anchors until
        # hydration. Harvest those URLs with the same series-relevance guards.
        series_slug = series_path.split("/")[-1].lower() if series_path else ""
        for absolute in _embedded_urls(tree, url):
            parsed = urlparse(absolute)
            if parsed.hostname != parsed_series.hostname:
                continue
            number = _chapter_number("", absolute)
            if not number or absolute in seen_urls:
                continue
            path_lower = parsed.path.lower().replace("_", "-")
            under_series_path = bool(series_path and parsed.path.startswith(series_path + "/"))
            root_slug_match = bool(series_slug and series_slug in path_lower)
            if series_path and not (under_series_path or root_slug_match):
                continue
            seen_urls.add(absolute)
            chapter_candidates.append(
                MangaChapter(
                    title=f"Chapter {number}",
                    slug=_chapter_slug(absolute, number),
                    chapter_number=number,
                    url=absolute,
                )
            )

        by_number: dict[str, MangaChapter] = {}
        for chapter in chapter_candidates:
            by_number.setdefault(
                chapter.chapter_number,
                chapter,
            )

        chapters = sorted(
            by_number.values(),
            key=lambda chapter: float(chapter.chapter_number),
        )

        if not chapters:
            raise ValueError(
                "No chapter links were discovered on the series page. "
                "The site may need a source-specific adapter."
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
            tags=tags,
            chapters=chapters,
        )

    def extract_chapter_pages(
        self,
        url: str,
        html: str,
    ) -> MangaChapterPages:
        tree = HTMLParser(html)

        title_node = (
            tree.css_first("h1")
            or tree.css_first("title")
        )

        raw_title = (
            title_node.text(strip=True)
            if title_node is not None
            else "Untitled Series"
        )

        chapter_number = (
            _chapter_number(raw_title, url)
            or "1"
        )

        series_title = re.split(
            r"(?:chapter|chap|ch\.?|episode|ep\.?)\s*[0-9]+(?:\.[0-9]+)?",
            raw_title,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" -|:")

        if not series_title:
            series_title = raw_title

        description = (
            _content(tree.css_first('meta[name="description"]'))
            or _content(tree.css_first('meta[property="og:description"]'))
        )

        cover_url = _content(
            tree.css_first('meta[property="og:image"]')
        )
        if cover_url:
            cover_url = urljoin(url, cover_url)

        candidates: list[str] = []
        seen: set[str] = set()

        preferred_selectors = [
            ".reader img",
            ".reading-content img",
            ".chapter-content img",
            ".page-break img",
            "#readerarea img",
            "#chapter-container img",
            "[class*='reader'] img",
            "[class*='chapter'] img",
            "main img",
            "article img",
        ]

        nodes = []
        seen_node_ids = set()

        for selector in preferred_selectors:
            for node in tree.css(selector):
                marker = id(node)
                if marker not in seen_node_ids:
                    seen_node_ids.add(marker)
                    nodes.append(node)

        # Last-resort broad image harvesting, equivalent to the old scraper's
        # generic image collection, but filtered below.
        if not nodes:
            nodes = list(tree.css("img"))

        for node in tree.css("picture source[srcset], picture source[data-srcset], [data-bg], [data-background], [data-background-image]"):
            marker = id(node)
            if marker not in seen_node_ids:
                seen_node_ids.add(marker)
                nodes.append(node)

        # Lazy-load plugins frequently leave the real image only in <noscript>.
        for noscript in tree.css("noscript"):
            fragment = noscript.text(strip=False) or ""
            if "<img" not in fragment.lower() and "<source" not in fragment.lower():
                continue
            nested = HTMLParser(html_lib.unescape(fragment))
            for node in nested.css("img, source[srcset], source[data-srcset]"):
                nodes.append(node)

        for node in nodes:
            src = _best_img_src(node)
            if not src:
                continue

            absolute = urljoin(url, src)
            parsed = urlparse(absolute)

            if parsed.scheme not in {"http", "https"}:
                continue

            alt = (node.attributes.get("alt") or "").lower()
            class_name = (node.attributes.get("class") or "").lower()

            # Skip common UI/noise assets.
            if any(
                token in (absolute + " " + alt + " " + class_name).lower()
                for token in (
                    "logo",
                    "avatar",
                    "icon",
                    "emoji",
                    "spinner",
                    "loading.gif",
                )
            ):
                continue

            if absolute in seen:
                continue

            seen.add(absolute)
            candidates.append(absolute)

        # App-state fallback for Next/Nuxt/SPA readers. Only direct image-like
        # URLs are accepted here to avoid importing recommendation/UI assets.
        for absolute in _embedded_urls(tree, url):
            lower = absolute.lower()
            if absolute in seen or (cover_url and absolute == cover_url):
                continue
            if any(token in lower for token in (
                "logo", "avatar", "icon", "emoji", "spinner", "banner",
                "favicon", "profile", "thumbnail", "thumb",
            )):
                continue
            if not _IMAGE_URL_RE.search(lower):
                continue
            seen.add(absolute)
            candidates.append(absolute)

        if not candidates:
            raise ValueError(
                "No chapter page images found. "
                "The site may need a source-specific adapter."
            )

        return MangaChapterPages(
            series=MangaSeries(
                title=series_title,
                slug=_slugify(series_title),
                description=description,
                cover_url=cover_url,
            ),
            chapter=MangaChapter(
                title=raw_title,
                slug=_chapter_slug(url, chapter_number),
                chapter_number=chapter_number,
                url=url,
            ),
            page_urls=candidates,
        )
