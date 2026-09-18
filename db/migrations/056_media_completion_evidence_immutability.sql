-- RC4.85 P06.3: seal Media publication completion evidence once recorded.
--
-- The application helper already treats completion evidence as write-once, but
-- Catalog relies on this row as durable publication proof. Enforce that
-- durability in PostgreSQL as well so a later Media update cannot rebind the
-- evidence to another ingestion operation, actor, source revision, generation,
-- manifest or page count. Unrelated Media diagnostics/result fields remain
-- updateable.

CREATE OR REPLACE FUNCTION enforce_media_completion_evidence_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.completion_evidence IS NOT NULL AND (
        NEW.completion_evidence IS DISTINCT FROM OLD.completion_evidence
        OR NEW.publication_operation_id IS DISTINCT FROM OLD.publication_operation_id
        OR NEW.publication_actor_id IS DISTINCT FROM OLD.publication_actor_id
        OR NEW.source_revision IS DISTINCT FROM OLD.source_revision
        OR NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256
        OR NEW.publication_page_count IS DISTINCT FROM OLD.publication_page_count
        OR NEW.media_generation IS DISTINCT FROM OLD.media_generation
        OR NEW.status IS DISTINCT FROM OLD.status
    ) THEN
        RAISE EXCEPTION 'media publication completion evidence is immutable once recorded'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_media_completion_evidence_immutability ON media_operations;
CREATE TRIGGER trg_media_completion_evidence_immutability
BEFORE UPDATE OF
    completion_evidence,
    publication_operation_id,
    publication_actor_id,
    source_revision,
    manifest_sha256,
    publication_page_count,
    media_generation,
    status
ON media_operations
FOR EACH ROW
EXECUTE FUNCTION enforce_media_completion_evidence_immutability();

COMMENT ON FUNCTION enforce_media_completion_evidence_immutability() IS
    'Prevents completed Media publication evidence from being rebound or invalidated after it is sealed.';
