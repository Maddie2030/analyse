import uuid
from app.rabbitmq import CHAPTER_QUEUE, THUMBNAIL_QUEUE, get_broker


def new_job_id() -> str:
    return str(uuid.uuid4())


async def enqueue_thumbnail_job(*, job_id: str, series_slug: str, source_path: str) -> None:
    await get_broker().publish(
        THUMBNAIL_QUEUE,
        job_id,
        {"series_slug": series_slug, "source_path": source_path},
    )


async def enqueue_chapter_job(
    *, job_id: str, series_slug: str, chapter_slug: str, source_path: str,
    filename: str, content_type: str, chapter_number: str, title: str | None,
    first_image_path: str | None = None, last_image_path: str | None = None,
) -> None:
    await get_broker().publish(
        CHAPTER_QUEUE,
        job_id,
        {
            "series_slug": series_slug,
            "chapter_slug": chapter_slug,
            "source_path": source_path,
            "filename": filename,
            "content_type": content_type,
            "chapter_number": chapter_number,
            "title": title,
            "first_image_path": first_image_path,
            "last_image_path": last_image_path,
        },
    )
