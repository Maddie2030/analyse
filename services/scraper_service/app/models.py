from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, HttpUrl


def _normalize_external_url(value):
    if isinstance(value, str):
        value = value.strip()
        if value and '://' not in value:
            value = 'https://' + value
    return value


ExternalHttpUrl = Annotated[HttpUrl, BeforeValidator(_normalize_external_url)]


ScrapeMode = Literal[
    "metadata",
    "text",
    "links",
    "images",
    "full",
]


class ScrapeRequest(BaseModel):
    url: ExternalHttpUrl
    mode: ScrapeMode = "full"
    save: bool = True
    store_raw_snapshot: bool = False


class ScrapeResponse(BaseModel):
    id: str | None = None
    adapter: str
    url: str
    mode: ScrapeMode
    title: str | None = None
    summary: str | None = None
    status: Literal["success", "error"] = "success"
    result: dict[str, Any]
    snapshot_path: str | None = None


class ChapterManifest(BaseModel):
    chapter_url: ExternalHttpUrl
    series_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    chapter_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    chapter_number: str
    title: str | None = None


class IngestChapterRequest(BaseModel):
    manifest: ChapterManifest


class ExistingSeriesDraftCreate(BaseModel):
    series_id: str
    chapter_url: ExternalHttpUrl


class DraftChapterUpdate(BaseModel):
    chapter_number: str
    chapter_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    chapter_title: str | None = None


class DraftPageFromUrl(BaseModel):
    url: ExternalHttpUrl
    position: int | None = Field(default=None, ge=1)


class DraftPageReorder(BaseModel):
    page_ids: list[str] = Field(min_length=1)


class DraftPageReplaceUrl(BaseModel):
    url: ExternalHttpUrl


class BatchConflictAction(BaseModel):
    action: Literal["discard", "overwrite"]


class BatchRetryAction(BaseModel):
    action: Literal["retry"] = "retry"


class NewSeriesDiscoverRequest(BaseModel):
    url: ExternalHttpUrl
    recursive: bool = True
    max_depth: int = Field(default=1, ge=0, le=3)
    max_pages: int = Field(default=20, ge=1, le=50)


class SeriesDraftUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    series_status: Literal[
        "ongoing",
        "completed",
        "hiatus",
        "cancelled",
    ] = "ongoing"
    genres: list[str] = []
    tags: list[str] = []


class SeriesDraftCoverUrl(BaseModel):
    url: ExternalHttpUrl


class SeriesDraftChapterUpdate(BaseModel):
    chapter_number: str
    chapter_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    chapter_title: str | None = None
    selected: bool = True


class SeriesDraftStageRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1)


class SeriesDraftPageReorder(BaseModel):
    page_ids: list[str] = Field(min_length=1)


class SeriesDraftPageUrl(BaseModel):
    url: ExternalHttpUrl
    position: int | None = Field(default=None, ge=1)

class DatabaseBackupTarget(BaseModel):
    backup_id: str


class DatabaseRestoreRequest(DatabaseBackupTarget):
    confirmation: str
    installation_fingerprint: str
    restore_generation: int = Field(ge=1)
