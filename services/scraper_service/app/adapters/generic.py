from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.adapters.base import AdapterResult, SourceAdapter


_IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-cfsrc",
    "data-url",
)


def _srcset_best(value: str | None) -> str | None:
    if not value:
        return None

    candidates = []
    for item in value.split(","):
        part = item.strip().split()
        if not part:
            continue
        score = 0
        if len(part) > 1:
            descriptor = part[-1].lower()
            try:
                if descriptor.endswith("w"):
                    score = int(descriptor[:-1])
                elif descriptor.endswith("x"):
                    score = int(float(descriptor[:-1]) * 1000)
            except ValueError:
                pass
        candidates.append((score, part[0]))

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item[0])[-1][1]


class GenericAdapter(SourceAdapter):
    name = "generic"

    def matches(self, url: str) -> bool:
        return True

    @staticmethod
    def _meta(tree: HTMLParser, selector: str) -> str | None:
        node = tree.css_first(selector)
        if node is None:
            return None
        return node.attributes.get("content") or node.text(strip=True) or None

    def extract(
        self,
        url: str,
        html: str,
        mode: str,
    ) -> AdapterResult:
        tree = HTMLParser(html)
        base = urlparse(url)

        title_node = tree.css_first("title")
        title = title_node.text(strip=True) if title_node else None

        description = (
            self._meta(tree, 'meta[name="description"]')
            or self._meta(tree, 'meta[property="og:description"]')
        )

        canonical_node = tree.css_first('link[rel="canonical"]')
        favicon_node = (
            tree.css_first('link[rel="icon"]')
            or tree.css_first('link[rel="shortcut icon"]')
        )

        metadata = {
            "title": title,
            "description": description,
            "og_title": self._meta(tree, 'meta[property="og:title"]'),
            "og_description": self._meta(
                tree,
                'meta[property="og:description"]',
            ),
            "og_image": self._meta(tree, 'meta[property="og:image"]'),
            "og_site_name": self._meta(
                tree,
                'meta[property="og:site_name"]',
            ),
            "og_type": self._meta(tree, 'meta[property="og:type"]'),
            "twitter_card": self._meta(tree, 'meta[name="twitter:card"]'),
            "twitter_title": self._meta(tree, 'meta[name="twitter:title"]'),
            "twitter_image": self._meta(tree, 'meta[name="twitter:image"]'),
            "keywords": self._meta(tree, 'meta[name="keywords"]'),
            "author": (
                self._meta(tree, 'meta[name="author"]')
                or self._meta(tree, 'meta[property="article:author"]')
            ),
            "canonical": (
                urljoin(url, canonical_node.attributes.get("href", ""))
                if canonical_node and canonical_node.attributes.get("href")
                else None
            ),
            "favicon": (
                urljoin(url, favicon_node.attributes.get("href", ""))
                if favicon_node and favicon_node.attributes.get("href")
                else None
            ),
            "lang": (
                tree.css_first("html").attributes.get("lang")
                if tree.css_first("html")
                else None
            ),
        }

        links: list[dict] = []
        internal: list[dict] = []
        external: list[dict] = []
        seen_links: set[str] = set()

        for node in tree.css("a[href]"):
            href = node.attributes.get("href")
            if not href:
                continue

            lowered = href.lower().strip()
            if lowered.startswith(
                ("#", "mailto:", "tel:", "javascript:", "data:")
            ):
                continue

            absolute = urljoin(url, href)
            parsed = urlparse(absolute)

            if parsed.scheme not in {"http", "https"}:
                continue

            if absolute in seen_links:
                continue

            seen_links.add(absolute)
            item = {
                "url": absolute,
                "text": node.text(strip=True) or None,
            }
            links.append(item)

            if parsed.hostname == base.hostname:
                internal.append(item)
            else:
                external.append(item)

        images: list[dict] = []
        seen_images: set[str] = set()

        for node in tree.css("img"):
            src = None
            for attr in _IMAGE_ATTRS:
                candidate = node.attributes.get(attr)
                if candidate:
                    src = candidate
                    break

            src = (
                _srcset_best(node.attributes.get("srcset"))
                or _srcset_best(node.attributes.get("data-srcset"))
                or src
            )

            if not src:
                continue

            absolute = urljoin(url, src)
            parsed = urlparse(absolute)

            if parsed.scheme not in {"http", "https"}:
                continue

            if absolute in seen_images:
                continue

            seen_images.add(absolute)
            images.append(
                {
                    "url": absolute,
                    "src": absolute,
                    "alt": node.attributes.get("alt"),
                    "width": node.attributes.get("width"),
                    "height": node.attributes.get("height"),
                    "loading": node.attributes.get("loading"),
                }
            )

        headings = []
        for level in range(1, 7):
            for node in tree.css(f"h{level}"):
                value = node.text(strip=True)
                if value:
                    headings.append({
                        "level": level,
                        "tag": f"h{level}",
                        "text": value,
                    })

        structured = []
        for selector in (
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "blockquote",
            "pre",
            "td",
            "th",
        ):
            for node in tree.css(selector):
                value = " ".join(node.text(separator=" ", strip=True).split())
                if len(value) > 1:
                    structured.append({
                        "tag": selector,
                        "text": value,
                    })

        stats = {
            "link_count": len(links),
            "internal_link_count": len(internal),
            "external_link_count": len(external),
            "image_count": len(images),
            "script_count": len(tree.css("script")),
            "style_count": len(tree.css("style")),
            "form_count": len(tree.css("form")),
            "table_count": len(tree.css("table")),
            "heading_count": len(headings),
        }

        for selector in ("script", "style", "noscript", "svg", "iframe"):
            for node in tree.css(selector):
                node.decompose()

        body = tree.css_first("body")
        text = body.text(separator=" ", strip=True) if body else ""
        text = " ".join(text.split())

        result: dict = {}

        if mode in {"metadata", "full"}:
            result["metadata"] = metadata
            result["headings"] = headings
            result["stats"] = stats

        if mode in {"links", "full"}:
            result["links"] = {
                "items": links,
                "all": links,
                "internal": internal,
                "external": external,
                "count": len(links),
                "internal_count": len(internal),
                "external_count": len(external),
            }

        if mode in {"images", "full"}:
            result["images"] = {
                "items": images,
                "images": images,
                "count": len(images),
            }

        if mode in {"text", "full"}:
            result["text"] = text
            result["full_text"] = text
            result["text_length"] = len(text)
            result["word_count"] = len(text.split())
            result["structured"] = structured

        return AdapterResult(
            title=title,
            summary=description or (text[:300] if text else None),
            result=result,
        )
