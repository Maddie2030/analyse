"""MReader v4 tile-pack codec.

One HTTP object contains independently compressed WebP tiles. Tiles are encoded
with overlap/context and then stored in a deterministic scrambled order. Because
lossy compression happens before scrambling and each tile keeps neighbor context,
we avoid the v2 seam bug while transferring far fewer bytes than v3 lossless.
"""
from __future__ import annotations

import hashlib
import secrets
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyvips

MAGIC = b"MRTILE4\0"
SALT_V4 = "mreader-v4-overlap-tilepack"
ENCODING_VERSION = 4
DEFAULT_ROWS = 4
DEFAULT_COLUMNS = 4
DEFAULT_OVERLAP = 12
HEADER = struct.Struct(">8sHHHHIII")
U32 = struct.Struct(">I")


@dataclass(frozen=True)
class TilePackMetadata:
    version: int
    rows: int
    columns: int
    seed: str


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _hash32(value: str) -> int:
    h = 2166136261
    for ch in value:
        h = _u32(h ^ ord(ch))
        h = _u32(h * 16777619)
    return h


class _Mulberry32:
    def __init__(self, seed: int) -> None:
        self.seed = _u32(seed)

    def random(self) -> float:
        self.seed = _u32(self.seed + 0x6D2B79F5)
        t = self.seed
        t = _u32((t ^ (t >> 15)) * (t | 1))
        t = _u32(t ^ _u32(t + _u32((t ^ (t >> 7)) * (t | 61))))
        return _u32(t ^ (t >> 14)) / 4294967296.0


def permutation_for_v4(count: int, chapter_seed: str, page_number: int) -> list[int]:
    material = f"{SALT_V4}:{chapter_seed}:page:{int(page_number)}:{count}"
    order = list(range(max(0, int(count))))
    rand = _Mulberry32(_hash32(material))
    for i in range(len(order) - 1, 0, -1):
        j = int(rand.random() * (i + 1))
        order[i], order[j] = order[j], order[i]
    return order


def slice_bounds(total: int, count: int, index: int) -> tuple[int, int]:
    p0 = (index * total) // count
    p1 = ((index + 1) * total) // count
    return p0, max(1, p1 - p0)


def new_seed() -> str:
    return secrets.token_hex(16)


def asset_version_for_v4(chapter_seed: str) -> str:
    seed = str(chapter_seed).strip()
    if not seed:
        raise ValueError("chapter_seed is required")
    return hashlib.sha256((SALT_V4 + ":" + seed).encode("utf-8")).hexdigest()[:20]


def _normalize_image(image: "pyvips.Image") -> "pyvips.Image":
    if image.interpretation not in ("srgb", "rgb", "b-w"):
        image = image.colourspace("srgb")
    if image.bands == 1:
        image = image.bandjoin([image, image])
    if image.bands == 2:
        gray = image[0]
        alpha = image[1]
        image = gray.bandjoin([gray, gray, alpha])
    if image.bands > 4:
        image = image.extract_band(0, n=3)
    return image


def encode_tilepack(
    image: "pyvips.Image",
    *,
    quality: int,
    rows: int = DEFAULT_ROWS,
    columns: int = DEFAULT_COLUMNS,
    overlap: int = DEFAULT_OVERLAP,
    seed: str,
    page_number: int,
) -> tuple[bytes, TilePackMetadata]:
    image = _normalize_image(image)
    rows = min(max(1, int(rows)), max(1, image.height))
    columns = min(max(1, int(columns)), max(1, image.width))
    overlap = min(max(0, int(overlap)), 64)
    total = rows * columns
    order = permutation_for_v4(total, seed, page_number)

    encoded_tiles: list[bytes] = []
    for encoded_index in range(total):
        original_index = order[encoded_index]
        row = original_index // columns
        col = original_index % columns
        x, width = slice_bounds(image.width, columns, col)
        y, height = slice_bounds(image.height, rows, row)
        left = max(0, x - overlap)
        top = max(0, y - overlap)
        right = min(image.width, x + width + overlap)
        bottom = min(image.height, y + height + overlap)
        tile = image.crop(left, top, right - left, bottom - top)
        encoded_tiles.append(tile.write_to_buffer(".webp", Q=int(quality), strip=True))

    header = HEADER.pack(
        MAGIC,
        rows,
        columns,
        overlap,
        0,
        image.width,
        image.height,
        total,
    )
    lengths = b"".join(U32.pack(len(tile)) for tile in encoded_tiles)
    return header + lengths + b"".join(encoded_tiles), TilePackMetadata(
        version=ENCODING_VERSION,
        rows=rows,
        columns=columns,
        seed=seed,
    )


def _parse(data: bytes) -> tuple[int, int, int, int, int, list[bytes]]:
    if len(data) < HEADER.size:
        raise ValueError("Tile-pack payload is truncated")
    magic, rows, columns, overlap, _reserved, width, height, total = HEADER.unpack_from(data, 0)
    if magic != MAGIC or rows < 1 or columns < 1 or total != rows * columns:
        raise ValueError("Invalid MReader v4 tile-pack header")
    if width < 1 or height < 1 or width > 20000 or height > 40000 or total > 1024:
        raise ValueError("Unsafe MReader v4 tile-pack dimensions")
    lengths_offset = HEADER.size
    payload_offset = lengths_offset + total * U32.size
    if payload_offset > len(data):
        raise ValueError("Tile-pack length table is truncated")
    lengths = [U32.unpack_from(data, lengths_offset + i * U32.size)[0] for i in range(total)]
    tiles: list[bytes] = []
    cursor = payload_offset
    for length in lengths:
        if length < 1 or cursor + length > len(data):
            raise ValueError("Tile-pack tile payload is truncated")
        tiles.append(data[cursor: cursor + length])
        cursor += length
    if cursor != len(data):
        raise ValueError("Tile-pack payload has trailing bytes")
    return rows, columns, overlap, width, height, tiles


def decode_tilepack(
    data: bytes,
    *,
    seed: str,
    page_number: int,
    quality: int = 94,
) -> bytes:
    """Decode v4 into a readable WebP for admin export/recovery."""
    import pyvips

    rows, columns, overlap, width, height, tiles = _parse(data)
    order = permutation_for_v4(rows * columns, seed, page_number)
    original_tiles: list[pyvips.Image | None] = [None] * (rows * columns)

    for encoded_index, raw in enumerate(tiles):
        try:
            tile = pyvips.Image.new_from_buffer(raw, "", page=0)
        except pyvips.Error:
            tile = pyvips.Image.new_from_buffer(raw, "")
        original_index = order[encoded_index]
        row = original_index // columns
        col = original_index % columns
        x, cell_width = slice_bounds(width, columns, col)
        y, cell_height = slice_bounds(height, rows, row)
        left = max(0, x - overlap)
        top = max(0, y - overlap)
        inner_x = x - left
        inner_y = y - top
        if tile.width < inner_x + cell_width or tile.height < inner_y + cell_height:
            raise ValueError("Tile-pack tile dimensions do not match metadata")
        original_tiles[original_index] = tile.crop(inner_x, inner_y, cell_width, cell_height)

    output_rows: list[pyvips.Image] = []
    for row in range(rows):
        cells = [original_tiles[row * columns + col] for col in range(columns)]
        if any(cell is None for cell in cells):
            raise ValueError("Tile-pack is missing a tile")
        typed = [cell for cell in cells if cell is not None]
        output_rows.append(typed[0] if len(typed) == 1 else pyvips.Image.arrayjoin(typed, across=len(typed), shim=0))
    decoded = output_rows[0] if len(output_rows) == 1 else pyvips.Image.arrayjoin(output_rows, across=1, shim=0)
    if decoded.width != width or decoded.height != height:
        raise ValueError("Decoded tile-pack dimensions do not match header")
    return decoded.write_to_buffer(".webp", Q=int(quality), strip=True)
