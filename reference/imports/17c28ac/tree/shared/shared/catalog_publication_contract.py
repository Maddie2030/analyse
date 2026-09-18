"""Publication v1 wire contract; no persistence, authentication or storage I/O.

Media evidence and Catalog receipts supplied here MUST come from their durable
owner, never from an HTTP caller. The actor argument MUST come from independent
active-admin authorization. These pure checks neither authenticate a workload
nor verify object bytes, cancellation/fences, database revisions or a commit.
Catalog must enforce those requirements when the command path is integrated.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .tilepack_codec import asset_version_for_v4

MAX_COMMAND_BYTES = 4 * 1024 * 1024
MAX_PAGES = 4096
MAX_INTEGER = 9007199254740991

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SEED = re.compile(r"[0-9a-f]{32}")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_CHAPTER_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,5})\.[0-9]{2}")
_COMMAND_FIELDS = frozenset({
    "schema_version", "idempotency_key", "operation_id", "actor_id",
    "source_revision", "ingestion_generation", "media_operation_id",
    "media_generation", "chapter_id", "expected_revision", "chapter_number",
    "title", "manifest",
})
_MANIFEST_FIELDS = frozenset({"schema_version", "series_id", "series_slug", "chapter_slug", "pages"})
_ASSET_FIELDS = frozenset({"image_path", "width", "height", "size_bytes", "sha256"})
_PAGE_FIELDS = _ASSET_FIELDS | {
    "page_number", "encoding_version", "encoding_rows", "encoding_columns",
    "encoding_seed", "responsive",
}
_MEDIA_FIELDS = frozenset({
    "schema_version", "status", "media_operation_id", "operation_id", "actor_id",
    "source_revision", "media_generation", "page_count", "manifest_sha256",
})
_RECEIPT_FIELDS = frozenset({
    "schema_version", "status", "idempotency_key", "operation_id", "actor_id",
    "payload_sha256", "series_id", "chapter_id", "chapter_revision",
    "series_revision", "page_count", "publication_event_id",
})


class PublicationContractError(ValueError):
    """Safe machine-readable contract failure; never includes private paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicationContractError(code)


def _object(value: Any, fields: frozenset | set, code: str) -> None:
    _require(type(value) is dict and value.keys() == fields, code)


def _integer(value: Any, code: str, minimum: int = 1, maximum: int = MAX_INTEGER) -> None:
    _require(type(value) is int and minimum <= value <= maximum, code)


def _pattern(value: Any, pattern: re.Pattern, code: str) -> None:
    _require(type(value) is str and pattern.fullmatch(value) is not None, code)


def _version(value: dict, code: str) -> None:
    _integer(value["schema_version"], code, 1, 1)


def _canonical_bytes(value: Any, code: str) -> bytes:
    try:
        # Wire v1 allows only integer numeric fields. Shape validation rejects
        # booleans/floats in those fields before any digest is accepted.
        return json.dumps(value, ensure_ascii=True, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("ascii")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise PublicationContractError(code) from None


def _snapshot(value: Any, code: str) -> dict:
    _require(type(value) is dict, code)
    raw = _canonical_bytes(value, code)
    _require(len(raw) <= MAX_COMMAND_BYTES, "request_too_large")
    # Copy without converting Python tuples/subclasses into different JSON
    # types. Semantic validation must see the types the caller submitted.
    try:
        return deepcopy(value)
    except RecursionError:
        raise PublicationContractError(code) from None


def _digest(value: dict) -> str:
    return hashlib.sha256(_canonical_bytes(value, "invalid_command")).hexdigest()


def _validate_asset(asset: dict, *, path: str, rows: int, columns: int) -> None:
    code = "invalid_manifest"
    _integer(asset["width"], code, 1, 20000)
    _integer(asset["height"], code, 1, 40000)
    _integer(asset["size_bytes"], code)
    _pattern(asset["sha256"], _SHA256, code)
    _require(asset["width"] >= columns and asset["height"] >= rows, code)
    _require(type(asset["image_path"]) is str and len(path) <= 500
             and asset["image_path"] == path, code)


def _validate_manifest(manifest: Any) -> None:
    code = "invalid_manifest"
    _object(manifest, _MANIFEST_FIELDS, code)
    _version(manifest, code)
    _pattern(manifest["series_id"], _UUID, code)
    _pattern(manifest["series_slug"], _SLUG, code)
    _pattern(manifest["chapter_slug"], _SLUG, code)
    _require(len(manifest["series_slug"]) <= 255 and len(manifest["chapter_slug"]) <= 255, code)
    pages = manifest["pages"]
    _require(type(pages) is list and len(pages) > 0, code)
    _require(len(pages) <= MAX_PAGES, "manifest_too_large")
    for number, page in enumerate(pages, 1):
        _object(page, _PAGE_FIELDS, code)
        _integer(page["page_number"], code, number, number)
        _integer(page["encoding_version"], code, 4, 4)
        _integer(page["encoding_rows"], code, 1, 32)
        _integer(page["encoding_columns"], code, 1, 32)
        _pattern(page["encoding_seed"], _SEED, code)
        rows, columns = page["encoding_rows"], page["encoding_columns"]
        version = asset_version_for_v4(page["encoding_seed"])
        prefix = f"{manifest['series_slug']}/{manifest['chapter_slug']}/_v4/{version}"
        _validate_asset(page, path=f"{prefix}/{number:04d}.mrt", rows=rows, columns=columns)
        responsive = page["responsive"]
        if responsive is not None:
            _object(responsive, _ASSET_FIELDS, code)
            # Format only a validated integer; caller strings/URLs never form a
            # storage path, and primary/responsive share the DB's v4 grid.
            _integer(responsive["width"], code, 1, 20000)
            _validate_asset(responsive,
                            path=f"{prefix}/w{responsive['width']}/{number:04d}.mrt",
                            rows=rows, columns=columns)
            _require(responsive["width"] < page["width"] and responsive["height"] <= page["height"], code)


def _validate_unsigned(command: dict) -> None:
    code = "invalid_command"
    _object(command, _COMMAND_FIELDS, code)
    _version(command, code)
    for name in ("idempotency_key", "operation_id", "actor_id", "media_operation_id"):
        _pattern(command[name], _UUID, code)
    for name in ("source_revision", "ingestion_generation", "media_generation"):
        _integer(command[name], code)
    _integer(command["expected_revision"], code, 0, MAX_INTEGER - 1)
    if command["chapter_id"] is None:
        _require(command["expected_revision"] == 0, code)
    else:
        _pattern(command["chapter_id"], _UUID, code)
        _require(command["expected_revision"] > 0, code)
    _pattern(command["chapter_number"], _CHAPTER_NUMBER, code)
    title = command["title"]
    if title is not None:
        _require(type(title) is str and len(title) <= 255, code)
        _require(all(ord(c) >= 32 and ord(c) != 127 and not 0xD800 <= ord(c) <= 0xDFFF for c in title), code)
    _validate_manifest(command["manifest"])


def seal_command(unsigned: dict) -> dict:
    """Return a detached, validated command bound to its entire submitted body."""
    command = _snapshot(unsigned, "invalid_command")
    _validate_unsigned(command)
    command["payload_sha256"] = _digest(command)
    _require(len(_canonical_bytes(command, "invalid_command")) <= MAX_COMMAND_BYTES, "request_too_large")
    return command


def validate_command(command: dict) -> dict:
    """Validate without normalization/rebasing; retain the transmitted identity."""
    result = _snapshot(command, "invalid_command")
    _object(result, _COMMAND_FIELDS | {"payload_sha256"}, "invalid_command")
    submitted = result.pop("payload_sha256")
    _pattern(submitted, _SHA256, "invalid_command")
    _validate_unsigned(result)
    _require(submitted == _digest(result), "payload_digest_mismatch")
    result["payload_sha256"] = submitted
    return result


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "invalid_command")
        result[key] = value
    return result


def _reject_number(raw: str) -> None:
    raise PublicationContractError("invalid_command")


def decode_command(raw: bytes) -> dict:
    """Reject oversized, ambiguous, fractional or non-finite raw JSON commands."""
    _require(type(raw) is bytes, "invalid_command")
    _require(len(raw) <= MAX_COMMAND_BYTES, "request_too_large")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except PublicationContractError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise PublicationContractError("invalid_command") from None
    return validate_command(value)


def manifest_digest(manifest: dict) -> str:
    result = _snapshot(manifest, "invalid_manifest")
    _validate_manifest(result)
    return _digest(result)


def _authorized_actor(command: dict, actor_id: str) -> None:
    _pattern(actor_id, _UUID, "actor_mismatch")
    _require(command["actor_id"] == actor_id, "actor_mismatch")


def validate_media_evidence(command: dict, receipt: dict, *, actor_id: str) -> dict:
    """Match independently loaded Media evidence; does not prove a publication."""
    result = validate_command(command)
    _authorized_actor(result, actor_id)
    evidence = _snapshot(receipt, "invalid_media_receipt")
    code = "invalid_media_receipt"
    _object(evidence, _MEDIA_FIELDS, code)
    _version(evidence, code)
    _require(evidence["status"] == "completed", "media_not_complete")
    for name in ("operation_id", "actor_id", "media_operation_id"):
        _pattern(evidence[name], _UUID, code)
    for name in ("source_revision", "media_generation", "page_count"):
        _integer(evidence[name], code, 1, MAX_PAGES if name == "page_count" else MAX_INTEGER)
    _pattern(evidence["manifest_sha256"], _SHA256, code)
    for name in ("operation_id", "actor_id", "media_operation_id", "source_revision", "media_generation"):
        _require(evidence[name] == result[name], "media_evidence_mismatch")
    _require(evidence["page_count"] == len(result["manifest"]["pages"])
             and evidence["manifest_sha256"] == _digest(result["manifest"]), "media_evidence_mismatch")
    return result


def replay_receipt(command: dict, receipt: dict, *, actor_id: str) -> dict:
    """Return the owner's recorded result or reject a conflicting retained key."""
    request = validate_command(command)
    _authorized_actor(request, actor_id)
    result = _snapshot(receipt, "invalid_catalog_receipt")
    code = "invalid_catalog_receipt"
    _object(result, _RECEIPT_FIELDS, code)
    _version(result, code)
    _require(result["status"] == "committed", code)
    for name in ("idempotency_key", "operation_id", "actor_id", "series_id", "chapter_id", "publication_event_id"):
        _pattern(result[name], _UUID, code)
    for name in ("chapter_revision", "series_revision", "page_count"):
        _integer(result[name], code, 1, MAX_PAGES if name == "page_count" else MAX_INTEGER)
    _pattern(result["payload_sha256"], _SHA256, code)
    for name in ("idempotency_key", "operation_id", "actor_id", "payload_sha256"):
        _require(result[name] == request[name], "idempotency_conflict")
    _require(result["series_id"] == request["manifest"]["series_id"], code)
    _require(request["chapter_id"] is None or result["chapter_id"] == request["chapter_id"], code)
    _require(result["page_count"] == len(request["manifest"]["pages"]), code)
    _require(result["chapter_revision"] == request["expected_revision"] + 1, code)
    return result
