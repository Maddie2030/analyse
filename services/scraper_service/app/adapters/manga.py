from abc import abstractmethod
from dataclasses import dataclass

from app.adapters.base import SourceAdapter


@dataclass
class MangaSeries:
    title: str
    slug: str
    description: str | None
    cover_url: str | None
    status: str = "ongoing"


@dataclass
class MangaChapter:
    title: str | None
    slug: str
    chapter_number: str
    url: str


@dataclass
class MangaChapterPages:
    series: MangaSeries
    chapter: MangaChapter
    page_urls: list[str]


@dataclass
class MangaSeriesManifest:
    series: MangaSeries
    genres: list[str]
    tags: list[str]
    chapters: list[MangaChapter]


class MangaSourceAdapter(SourceAdapter):
    @abstractmethod
    def extract_chapter_pages(
        self,
        url: str,
        html: str,
    ) -> MangaChapterPages:
        raise NotImplementedError

    @abstractmethod
    def extract_series_manifest(
        self,
        url: str,
        html: str,
    ) -> MangaSeriesManifest:
        raise NotImplementedError
