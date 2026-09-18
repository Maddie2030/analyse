import io
import os
import logging
import math
import re
import zipfile
from pathlib import Path

import pyvips

# Bound libvips process-local caches. Combined with VIPS_CONCURRENCY this keeps
# multiple media/scraper jobs from oversubscribing CPU or retaining unbounded
# decoded image state between requests.
try:
    pyvips.cache_set_max(max(0, int(os.getenv("VIPS_CACHE_MAX_OPS", "100"))))
    pyvips.cache_set_max_mem(max(0, int(os.getenv("VIPS_CACHE_MAX_MEM_MB", "128"))) * 1024 * 1024)
    pyvips.cache_set_max_files(max(0, int(os.getenv("VIPS_CACHE_MAX_FILES", "50"))))
except (AttributeError, ValueError):
    pass

from shared import settings
from shared.tilepack_codec import (
    DEFAULT_COLUMNS as V4_DEFAULT_COLUMNS,
    DEFAULT_OVERLAP as V4_DEFAULT_OVERLAP,
    DEFAULT_ROWS as V4_DEFAULT_ROWS,
    asset_version_for_v4,
    encode_tilepack,
    new_seed,
)
from app.media_config import LIMITS

log = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", 
    ".tiff", ".tif", ".webp", ".avif", ".heic", ".ppm"
}
WEBP_QUALITY = LIMITS.webp_quality
WEBP_MAX_DIMENSION = LIMITS.max_segment_height
MAX_UNCOMPRESSED_PAGE_SIZE = LIMITS.max_uncompressed_page_size_bytes
PAGE_MAX_WIDTH = max(0, int(getattr(settings, "PAGE_MAX_WIDTH", 1080)))
PAGE_RESPONSIVE_WIDTH = max(0, int(getattr(settings, "PAGE_RESPONSIVE_WIDTH", 720)))
PAGE_ENCODING_V4_ROWS = max(1, int(getattr(settings, "PAGE_ENCODING_V4_ROWS", V4_DEFAULT_ROWS)))
PAGE_ENCODING_V4_COLUMNS = max(1, int(getattr(settings, "PAGE_ENCODING_V4_COLUMNS", V4_DEFAULT_COLUMNS)))
PAGE_ENCODING_V4_OVERLAP = max(0, int(getattr(settings, "PAGE_ENCODING_V4_OVERLAP", V4_DEFAULT_OVERLAP)))


def _page_relative_path(series_slug: str, chapter_slug: str, page_number: int, chapter_seed: str, encoding_version: int = 4, variant: str | None = None) -> str:
    if int(encoding_version) != 4:
        raise ValueError(f"Fresh baseline supports only page encoding v4, got {encoding_version}")
    variant_part = f"/{variant}" if variant else ""
    return (
        f"images/{series_slug}/{chapter_slug}/_v4/"
        f"{asset_version_for_v4(chapter_seed)}{variant_part}/{page_number:04d}.mrt"
    )


def _prepare_reader_image(image: pyvips.Image) -> pyvips.Image:
    if PAGE_MAX_WIDTH > 0 and image.width > PAGE_MAX_WIDTH:
        image = image.resize(PAGE_MAX_WIDTH / image.width, kernel="lanczos3")
    return image


def _encode_reader_page(image: pyvips.Image, chapter_seed: str, page_number: int) -> tuple[bytes, object, str]:
    data, meta = encode_tilepack(
        image,
        quality=WEBP_QUALITY,
        rows=PAGE_ENCODING_V4_ROWS,
        columns=PAGE_ENCODING_V4_COLUMNS,
        overlap=PAGE_ENCODING_V4_OVERLAP,
        seed=chapter_seed,
        page_number=page_number,
    )
    return data, meta, "application/vnd.mreader.tilepack"



def _responsive_variant(image: pyvips.Image, chapter_seed: str, page_number: int) -> dict | None:
    """Encode one optional mobile/bandwidth-saving v4 derivative.

    Every published page and derivative uses the v4 tile-pack contract.
    """
    if PAGE_RESPONSIVE_WIDTH <= 0 or image.width <= PAGE_RESPONSIVE_WIDTH:
        return None
    small = image.resize(PAGE_RESPONSIVE_WIDTH / image.width, kernel="lanczos3")
    data, encoding, content_type = _encode_reader_page(small, chapter_seed, page_number)
    return {
        "image_path": None,
        "width": small.width,
        "height": small.height,
        "data": data,
        "content_type": content_type,
        "encoding_version": encoding.version,
    }

def _is_image_file(filename: str) -> bool:
    path = Path(filename)
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS and not path.name.startswith("._")


def _natural_sort_key(filename: str) -> tuple:
    base_name = Path(filename).name
    parts = re.split(r"(\d+)", base_name)
    result = []
    for part in parts:
        if part.isdigit():
            result.append((0, int(part)))
        else:
            result.append((1, part.lower()))
    return tuple(result)


def _load_vips_image_safe(image_data: bytes) -> pyvips.Image:
    """Load and eagerly materialize one image frame into memory.

    libvips normally evaluates lazily. A sequential PNG/JPEG loader can fail with
    "out of order read" when the same source graph is traversed more than once
    for primary/responsive derivatives. Materializing once makes derivative work
    deterministic while still bounding memory through the worker/container limits.
    """
    try:
        image = pyvips.Image.new_from_buffer(image_data, "", page=0, access="sequential")
    except pyvips.Error:
        image = pyvips.Image.new_from_buffer(image_data, "", access="sequential")
    return image.copy_memory()


def _retain_icc_metadata_only(image: pyvips.Image) -> pyvips.Image:
    """Preserve the embedded ICC profile without relying on saver keep=.

    The Docker images pin libvips 8.14.x, whose WebP saver does not expose
    the newer ``keep`` option. Removing non-ICC metadata on a private copy
    preserves the previous keep=icc behavior without leaking EXIF/XMP data.
    """
    output = image.copy()
    for field in output.get_fields():
        if field != "icc-profile-data":
            output.remove(field)
    return output


def convert_image_to_webp(image_data: bytes) -> tuple[bytes, int, int]:
    image = _load_vips_image_safe(image_data)
    webp_data = _retain_icc_metadata_only(image).write_to_buffer(
        ".webp", Q=WEBP_QUALITY
    )
    return webp_data, image.width, image.height


def _convert_vips_image_to_segments(
    image: pyvips.Image,
    series_slug: str,
    chapter_slug: str,
    page_number: int,
    chapter_seed: str,
) -> list[dict]:
    image = _prepare_reader_image(image)

    if image.height <= WEBP_MAX_DIMENSION:
        webp_data, encoding, content_type = _encode_reader_page(
            image, chapter_seed, page_number
        )
        relative_path = _page_relative_path(series_slug, chapter_slug, page_number, chapter_seed, encoding.version)
        responsive = _responsive_variant(image, chapter_seed, page_number)
        if responsive is not None:
            responsive["image_path"] = _page_relative_path(
                series_slug, chapter_slug, page_number, chapter_seed,
                responsive["encoding_version"],
                variant=f"w{responsive['width']}",
            )
        return [{
            "page_number": page_number,
            "image_path": relative_path,
            "width": image.width,
            "height": image.height,
            "file_size": len(webp_data),
            "data": webp_data,
            "content_type": content_type,
            "responsive": responsive,
            "encoding_version": encoding.version,
            "encoding_rows": encoding.rows,
            "encoding_columns": encoding.columns,
            "encoding_seed": encoding.seed,
        }]

    segment_height = WEBP_MAX_DIMENSION
    num_segments = math.ceil(image.height / segment_height)
    segments = []

    for i in range(num_segments):
        top = i * segment_height
        actual_height = min(segment_height, image.height - top)

        segment = image.crop(0, top, image.width, actual_height)
        segment_page_number = page_number + i
        webp_data, encoding, content_type = _encode_reader_page(
            segment, chapter_seed, segment_page_number
        )

        relative_path = _page_relative_path(series_slug, chapter_slug, segment_page_number, chapter_seed, encoding.version)
        responsive = _responsive_variant(segment, chapter_seed, segment_page_number)
        if responsive is not None:
            responsive["image_path"] = _page_relative_path(
                series_slug, chapter_slug, segment_page_number, chapter_seed,
                responsive["encoding_version"],
                variant=f"w{responsive['width']}",
            )

        segments.append({
            "page_number": segment_page_number,
            "image_path": relative_path,
            "width": image.width,
            "height": actual_height,
            "file_size": len(webp_data),
            "data": webp_data,
            "content_type": content_type,
            "responsive": responsive,
            "encoding_version": encoding.version,
            "encoding_rows": encoding.rows,
            "encoding_columns": encoding.columns,
            "encoding_seed": encoding.seed,
        })

    return segments


def _convert_tall_image_to_segments(
    image_data: bytes,
    series_slug: str,
    chapter_slug: str,
    page_number: int,
    chapter_seed: str,
) -> list[dict]:
    return _convert_vips_image_to_segments(
        _load_vips_image_safe(image_data),
        series_slug,
        chapter_slug,
        page_number,
        chapter_seed,
    )


def process_single_image(
    image_data: bytes,
    series_slug: str,
    chapter_slug: str,
    start_page_number: int,
    chapter_seed: str | None = None,
) -> list[dict]:
    """Process one optional chapter boundary image through the same WebP/tall-page pipeline."""
    return _convert_tall_image_to_segments(
        image_data,
        series_slug,
        chapter_slug,
        start_page_number,
        chapter_seed or new_seed(),
    )


def _iter_archive_source(
    source,
    series_slug: str,
    chapter_slug: str,
    *,
    start_page_number: int = 1,
    chapter_seed: str | None = None,
):
    """Yield ZIP/CBZ pages incrementally from bytes, a path, or file object.

    Only the current compressed archive member plus its encoded page/segments
    are retained. Consumers can upload each yielded page immediately instead of
    accumulating the complete encoded chapter in RAM.
    """
    chapter_seed = chapter_seed or new_seed()

    with zipfile.ZipFile(source, "r") as zf:
        image_files = sorted(
            [f for f in zf.namelist() if _is_image_file(f) and not f.startswith("__MACOSX")],
            key=_natural_sort_key,
        )
        if not image_files:
            raise ValueError("No supported image files found in the archive.")

        next_page_number = int(start_page_number)
        for filename in image_files:
            info = zf.getinfo(filename)
            if info.file_size > MAX_UNCOMPRESSED_PAGE_SIZE:
                raise ValueError(f"File '{filename}' exceeds uncompressed size safety limit.")

            raw_data = zf.read(filename)
            try:
                segment_pages = _convert_tall_image_to_segments(
                    raw_data, series_slug, chapter_slug, next_page_number, chapter_seed,
                )
            except Exception as e:
                raise ValueError(f"Failed to convert '{filename}': {e}")

            for page in segment_pages:
                yield page
            next_page_number += len(segment_pages)


def iter_archive_bytes(
    archive_data: bytes, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
):
    yield from _iter_archive_source(
        io.BytesIO(archive_data), series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    )


def iter_archive_file(
    archive_path: str | Path, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
):
    yield from _iter_archive_source(
        str(archive_path), series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    )


def iter_archive_stream(
    archive_file, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
):
    try:
        archive_file.seek(0)
    except (AttributeError, OSError):
        pass
    yield from _iter_archive_source(
        archive_file, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    )


def process_archive(
    archive_data: bytes, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
) -> list[dict]:
    return list(iter_archive_bytes(
        archive_data, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    ))


def process_archive_file(
    archive_path: str | Path, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
) -> list[dict]:
    return list(iter_archive_file(
        archive_path, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    ))


def process_archive_stream(
    archive_file, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
) -> list[dict]:
    return list(iter_archive_stream(
        archive_file, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    ))


def _iter_pdf_source(
    source,
    *,
    from_file: bool,
    series_slug: str,
    chapter_slug: str,
    start_page_number: int = 1,
    chapter_seed: str | None = None,
):
    """Yield rendered PDF pages one at a time from memory or a file path."""
    chapter_seed = chapter_seed or new_seed()

    def open_page(*, page: int | None = None, n: int | None = None):
        kwargs = {}
        if page is not None:
            kwargs.update(page=page, dpi=300)
        if n is not None:
            kwargs["n"] = n
        if from_file:
            return pyvips.Image.new_from_file(str(source), **kwargs)
        return pyvips.Image.new_from_buffer(source, "", **kwargs)

    try:
        doc = open_page(n=-1)
        total_pages = doc.get_n_pages()
    except Exception as e:
        raise ValueError(f"Failed to parse PDF document: {e}")

    if total_pages <= 0:
        raise ValueError("PDF document contains no valid pages.")

    next_page_number = int(start_page_number)
    for page_idx in range(total_pages):
        try:
            page_img = open_page(page=page_idx).copy_memory()
            segment_pages = _convert_vips_image_to_segments(
                page_img, series_slug, chapter_slug, next_page_number, chapter_seed
            )
            for page in segment_pages:
                yield page
            next_page_number += len(segment_pages)
        except Exception as e:
            raise ValueError(f"Failed to render PDF page {page_idx + 1}: {e}")


def iter_pdf_bytes(
    pdf_data: bytes, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
):
    yield from _iter_pdf_source(
        pdf_data, from_file=False, series_slug=series_slug, chapter_slug=chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    )


def iter_pdf_file(
    pdf_path: str | Path, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
):
    yield from _iter_pdf_source(
        str(pdf_path), from_file=True, series_slug=series_slug, chapter_slug=chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    )


def process_pdf(
    pdf_data: bytes, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
) -> list[dict]:
    return list(iter_pdf_bytes(
        pdf_data, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    ))


def process_pdf_file(
    pdf_path: str | Path, series_slug: str, chapter_slug: str,
    *, start_page_number: int = 1, chapter_seed: str | None = None,
) -> list[dict]:
    return list(iter_pdf_file(
        pdf_path, series_slug, chapter_slug,
        start_page_number=start_page_number, chapter_seed=chapter_seed,
    ))
