import os
from dataclasses import dataclass


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class MediaLimits:
    max_upload_size_bytes: int
    max_thumbnail_size_bytes: int
    max_uncompressed_page_size_bytes: int
    webp_quality: int
    max_segment_height: int


LIMITS = MediaLimits(
    max_upload_size_bytes=_bounded_int("MAX_UPLOAD_SIZE_MB", 500, 1, 4096) * 1024 * 1024,
    max_thumbnail_size_bytes=_bounded_int("MAX_THUMBNAIL_SIZE_MB", 10, 1, 100) * 1024 * 1024,
    max_uncompressed_page_size_bytes=_bounded_int("MAX_UNCOMPRESSED_PAGE_SIZE_MB", 100, 8, 1024) * 1024 * 1024,
    webp_quality=_bounded_int("PAGE_WEBP_QUALITY", 85, 40, 100),
    # 8192 keeps a 1080px-wide decoded canvas under ~9 MP while avoiding the
    # request explosion caused by the previous 1024px segment ceiling.
    max_segment_height=_bounded_int("PAGE_MAX_SEGMENT_HEIGHT", 8192, 1024, 16384),
)
