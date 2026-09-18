import re

SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
THUMBNAIL_NAME = re.compile(r"^thumbnail-[a-f0-9]+\.webp$")

IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/avif",
    "image/heic",
    "image/x-ms-bmp",
    "application/octet-stream",
}

ARCHIVE_MIME_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-cbz",
    "application/pdf",
    "application/octet-stream",
}
