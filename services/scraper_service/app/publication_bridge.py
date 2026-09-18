from __future__ import annotations

import io
import mimetypes
import zipfile
from typing import Any, BinaryIO, Iterable


async def _lock_ingestion_operation_tx(conn, operation_id: str) -> None:
    """Serialize Scraper recovery/cancel with Catalog's publication decision."""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 485063))",
        operation_id,
    )


async def _catalog_receipt_for_operation_tx(conn, operation_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT operation_id::text, chapter_id::text, result
        FROM catalog_mutation_receipts
        WHERE operation_id=$1::uuid
        ORDER BY created_at DESC
        LIMIT 1
        """,
        operation_id,
    )
    if row is None:
        return None
    value = dict(row)
    receipt = value.get("result")
    if isinstance(receipt, dict):
        value["receipt"] = receipt
    return value


async def _current_ingestion_outcome_tx(conn, operation_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id::text,source_kind,requesting_actor_id::text,status,phase,
               source_revision,revision,lease_generation,cancel_requested_at
        FROM ingestion_operations
        WHERE id=$1::uuid
        """,
        operation_id,
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "source_kind": row["source_kind"],
        "requesting_actor_id": str(row["requesting_actor_id"]),
        "status": row["status"],
        "phase": row["phase"],
        "source_revision": int(row["source_revision"]),
        "revision": int(row["revision"]),
        "lease_generation": int(row["lease_generation"]),
        "cancel_requested_at": row["cancel_requested_at"],
    }


async def _committed_ingestion_outcome_tx(conn, operation_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    await conn.execute(
        """
        UPDATE ingestion_operations
        SET status='completed',phase='catalog_commit',published_count=GREATEST(published_count,1),
            error_code=NULL,updated_at=NOW()
        WHERE id=$1::uuid
        """,
        operation_id,
    )
    current = await _current_ingestion_outcome_tx(conn, operation_id) or {"id": operation_id}
    current.update(
        {
            "status": "completed",
            "committed": True,
            "receipt": receipt.get("receipt") or receipt.get("result") or receipt,
            "chapter_id": receipt.get("chapter_id"),
        }
    )
    return current


async def recover_ingestion_operation_lease_tx(conn, operation_id: str) -> dict[str, Any] | None:
    """Recover one stale Scraper attempt under Catalog's publication fence."""
    await _lock_ingestion_operation_tx(conn, operation_id)
    receipt = await _catalog_receipt_for_operation_tx(conn, operation_id)
    if receipt is not None:
        return await _committed_ingestion_outcome_tx(conn, operation_id, receipt)

    row = await conn.fetchrow(
        """
        UPDATE ingestion_operations
        SET lease_generation=lease_generation+1,
            revision=revision+1,
            status='running',phase='media_transform',error_code=NULL,updated_at=NOW()
        WHERE id=$1::uuid
          AND status='running'
          AND cancel_requested_at IS NULL
        RETURNING id::text,source_kind,requesting_actor_id::text,status,phase,
                  source_revision,revision,lease_generation,cancel_requested_at
        """,
        operation_id,
    )
    if row is not None:
        outcome = dict(row)
        outcome["recovered"] = True
        return outcome
    return await _current_ingestion_outcome_tx(conn, operation_id)


async def cancel_ingestion_operation_tx(conn, operation_id: str) -> dict[str, Any] | None:
    """Cancel one canonical ingestion attempt unless Catalog already committed it."""
    await _lock_ingestion_operation_tx(conn, operation_id)
    receipt = await _catalog_receipt_for_operation_tx(conn, operation_id)
    if receipt is not None:
        return await _committed_ingestion_outcome_tx(conn, operation_id, receipt)

    row = await conn.fetchrow(
        """
        UPDATE ingestion_operations
        SET cancel_requested_at=COALESCE(cancel_requested_at,NOW()),
            status='cancelled',phase='cancelled',revision=revision+1,updated_at=NOW()
        WHERE id=$1::uuid
          AND status NOT IN ('completed','completed_with_errors','failed','cancelled')
        RETURNING id::text,source_kind,requesting_actor_id::text,status,phase,
                  source_revision,revision,lease_generation,cancel_requested_at
        """,
        operation_id,
    )
    if row is not None:
        return dict(row)
    return await _current_ingestion_outcome_tx(conn, operation_id)


def append_staged_chapter_page(
    archive: zipfile.ZipFile,
    order: int,
    data: bytes,
    content_type: str,
) -> None:
    """Append one raw staged page to a Media-bound archive without transformation."""
    ext = mimetypes.guess_extension(content_type or "") or ".img"
    if ext == ".jpe":
        ext = ".jpg"
    archive.writestr(f"{int(order):04d}{ext}", data)


def build_staged_chapter_archive(pages: Iterable[tuple[int, bytes, str]]) -> bytes:
    """Package already-staged raw pages without performing Media transformation."""
    ordered = sorted(pages, key=lambda item: int(item[0]))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for order, data, content_type in ordered:
            append_staged_chapter_page(zf, order, data, content_type)
    return buffer.getvalue()


async def _validate_parent_ingestion_operation_tx(
    conn,
    *,
    parent_operation_id: str | None,
    source_kind: str,
    requesting_actor_id: str,
) -> None:
    if parent_operation_id is None:
        return
    parent = await conn.fetchrow(
        """
        SELECT source_kind,requesting_actor_id::text,status,cancel_requested_at
        FROM ingestion_operations
        WHERE id=$1::uuid
        FOR SHARE
        """,
        parent_operation_id,
    )
    if parent is None:
        raise RuntimeError("parent ingestion operation is missing")
    if parent["source_kind"] != source_kind:
        raise RuntimeError("parent ingestion operation source kind does not match")
    if str(parent["requesting_actor_id"]) != str(requesting_actor_id):
        raise RuntimeError("parent ingestion operation is owned by another requesting actor")
    if parent["status"] in {"cancel_requested", "cancelled"} or parent["cancel_requested_at"] is not None:
        raise RuntimeError("parent ingestion operation is cancelled")


def _validate_ingestion_operation_owner(
    value: dict[str, Any],
    *,
    source_kind: str,
    requesting_actor_id: str,
) -> None:
    if value["source_kind"] != source_kind:
        raise RuntimeError("ingestion operation source kind does not match")
    if str(value["requesting_actor_id"]) != str(requesting_actor_id):
        raise RuntimeError("ingestion operation is owned by another requesting actor")


async def _attach_parent_ingestion_operation_tx(
    conn,
    *,
    operation_id: str,
    value: dict[str, Any],
    parent_operation_id: str | None,
) -> dict[str, Any]:
    if parent_operation_id is None:
        return value
    existing_parent = value.get("parent_operation_id")
    if existing_parent not in {None, parent_operation_id}:
        raise RuntimeError("ingestion operation is linked to another parent operation")
    if existing_parent is not None:
        return value
    row = await conn.fetchrow(
        """
        UPDATE ingestion_operations
        SET parent_operation_id=$2::uuid,updated_at=NOW()
        WHERE id=$1::uuid
        RETURNING id::text,source_kind,requesting_actor_id::text,parent_operation_id::text,
                  status,phase,source_revision,lease_generation
        """,
        operation_id,
        parent_operation_id,
    )
    return dict(row)


async def _resume_ingestion_operation_tx(
    conn,
    *,
    operation_id: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    if value["status"] in {"cancel_requested", "cancelled"}:
        raise RuntimeError("ingestion operation is cancelled")
    if value["status"] in {"completed", "completed_with_errors"}:
        return value
    row = await conn.fetchrow(
        """
        UPDATE ingestion_operations
        SET status='running',phase='media_transform',updated_at=NOW()
        WHERE id=$1::uuid
        RETURNING id::text,source_kind,requesting_actor_id::text,parent_operation_id::text,
                  status,phase,source_revision,lease_generation
        """,
        operation_id,
    )
    return dict(row)


async def ensure_ingestion_operation(
    pool, *, operation_id: str, source_kind: str, requesting_actor_id: str,
    parent_operation_id: str | None = None,
) -> dict[str, Any]:
    """Create/reuse the Scraper-owned publication fence for one draft attempt."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _validate_parent_ingestion_operation_tx(
                conn, parent_operation_id=parent_operation_id, source_kind=source_kind,
                requesting_actor_id=requesting_actor_id,
            )
            row = await conn.fetchrow(
                """
                SELECT id::text,source_kind,requesting_actor_id::text,parent_operation_id::text,
                       status,phase,source_revision,lease_generation
                FROM ingestion_operations
                WHERE id=$1::uuid
                FOR UPDATE
                """,
                operation_id,
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    INSERT INTO ingestion_operations(
                        id,source_kind,requesting_actor_id,parent_operation_id,status,phase,
                        source_revision,revision,lease_generation,selected_count,staged_count
                    ) VALUES(
                        $1::uuid,$2,$3::uuid,$4::uuid,'running','media_transform',1,1,1,1,1
                    )
                    RETURNING id::text,source_kind,requesting_actor_id::text,parent_operation_id::text,
                              status,phase,source_revision,lease_generation
                    """,
                    operation_id, source_kind, requesting_actor_id, parent_operation_id,
                )
                return dict(row)
            value = dict(row)
            _validate_ingestion_operation_owner(
                value, source_kind=source_kind, requesting_actor_id=requesting_actor_id,
            )
            value = await _attach_parent_ingestion_operation_tx(
                conn, operation_id=operation_id, value=value,
                parent_operation_id=parent_operation_id,
            )
            return await _resume_ingestion_operation_tx(conn, operation_id=operation_id, value=value)
