package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"mreader/catalog/internal/model"
)

var ErrIdempotencyConflict = errors.New("idempotency conflict")
var ErrStaleCatalogRevision = errors.New("stale catalog revision")
var ErrMediaEvidenceMismatch = errors.New("media completion evidence mismatch")
var ErrPublicationActorUnauthorized = errors.New("publication actor unauthorized")
var ErrStaleIngestionSourceRevision = errors.New("stale ingestion source revision")
var ErrStaleIngestionGeneration = errors.New("stale ingestion generation")
var ErrIngestionCancelled = errors.New("ingestion cancelled")
var ErrIngestionNotRunning = errors.New("ingestion is not running")

type publicationIngestionAuthority struct {
	ActorID           string
	SourceRevision    int64
	LeaseGeneration   int64
	Status            string
	CancelRequestedAt *time.Time
}

// lockPublicationIngestionOperationTx serializes Catalog publication decisions
// with the ingestion coordinator without requiring UPDATE privilege on the
// Scraper-owned ingestion_operations table. P07 cancellation/lease mutations
// must take this same transaction advisory fence before changing the header.
func lockPublicationIngestionOperationTx(ctx context.Context, tx pgx.Tx, operationID string) error {
	_, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 485063))`, operationID)
	return err
}

func publicationIngestionAuthorityTx(ctx context.Context, tx pgx.Tx, operationID string) (publicationIngestionAuthority, error) {
	var out publicationIngestionAuthority
	err := tx.QueryRow(ctx, `
		SELECT requesting_actor_id::text, source_revision, lease_generation, status, cancel_requested_at
		FROM ingestion_operations
		WHERE id=$1::uuid`, operationID,
	).Scan(&out.ActorID, &out.SourceRevision, &out.LeaseGeneration, &out.Status, &out.CancelRequestedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return publicationIngestionAuthority{}, ErrConflict
	}
	if err != nil {
		return publicationIngestionAuthority{}, err
	}
	return out, nil
}

func publicationActorAuthorizedTx(ctx context.Context, tx pgx.Tx, actorID string) (bool, error) {
	var role string
	var isActive bool
	err := tx.QueryRow(ctx, `
		SELECT role, is_active
		FROM users
		WHERE id=$1::uuid`, actorID,
	).Scan(&role, &isActive)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !isActive || role != "admin" {
		return false, nil
	}
	return true, nil
}

func validatePublicationIngestionAuthority(command model.PublicationCommand, authority publicationIngestionAuthority) error {
	if authority.ActorID != command.ActorID {
		return ErrPublicationActorUnauthorized
	}
	if authority.SourceRevision != command.SourceRevision {
		return ErrStaleIngestionSourceRevision
	}
	if authority.LeaseGeneration != command.IngestionGeneration {
		return ErrStaleIngestionGeneration
	}
	if authority.CancelRequestedAt != nil || authority.Status == "cancel_requested" || authority.Status == "cancelled" {
		return ErrIngestionCancelled
	}
	if authority.Status != "running" {
		return ErrIngestionNotRunning
	}
	return nil
}

func publicationReceiptTx(ctx context.Context, tx pgx.Tx, idempotencyKey string) (model.CatalogMutationReceipt, bool, error) {
	var out model.CatalogMutationReceipt
	err := tx.QueryRow(ctx, `
		SELECT idempotency_key::text, operation_id::text, actor_id::text,
		       payload_sha256, series_id::text, chapter_id::text,
		       chapter_revision, series_revision, page_count,
		       publication_event_id::text
		FROM catalog_mutation_receipts
		WHERE idempotency_key=$1::uuid
		FOR UPDATE`, idempotencyKey,
	).Scan(
		&out.IdempotencyKey, &out.OperationID, &out.ActorID, &out.PayloadSHA256,
		&out.SeriesID, &out.ChapterID, &out.ChapterRevision, &out.SeriesRevision,
		&out.PageCount, &out.PublicationEventID,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.CatalogMutationReceipt{}, false, nil
	}
	if err != nil {
		return model.CatalogMutationReceipt{}, false, err
	}
	out.SchemaVersion = 1
	out.Status = "committed"
	return out, true, nil
}

func publicationEvidenceTx(ctx context.Context, tx pgx.Tx, mediaOperationID string) (model.MediaCompletionEvidence, error) {
	var out model.MediaCompletionEvidence
	err := tx.QueryRow(ctx, `
		SELECT media_operation_id::text, operation_id::text, actor_id::text,
		       source_revision, media_generation, page_count, manifest_sha256
		FROM media_completion_evidence_v1
		WHERE media_operation_id=$1::uuid`, mediaOperationID,
	).Scan(
		&out.MediaOperationID, &out.OperationID, &out.ActorID, &out.SourceRevision,
		&out.MediaGeneration, &out.PageCount, &out.ManifestSHA256,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.MediaCompletionEvidence{}, ErrMediaEvidenceMismatch
	}
	if err != nil {
		return model.MediaCompletionEvidence{}, err
	}
	out.SchemaVersion = 1
	out.Status = "completed"
	return out, nil
}

func validatePublicationEvidence(command model.PublicationCommand, evidence model.MediaCompletionEvidence) error {
	if evidence.Status != "completed" ||
		evidence.MediaOperationID != command.MediaOperationID ||
		evidence.OperationID != command.OperationID ||
		evidence.ActorID != command.ActorID ||
		evidence.SourceRevision != command.SourceRevision ||
		evidence.MediaGeneration != command.MediaGeneration ||
		evidence.PageCount != len(command.Manifest.Pages) ||
		evidence.ManifestSHA256 != command.ManifestSHA256 {
		return ErrMediaEvidenceMismatch
	}
	return nil
}

func publicationCleanupPayloadTx(ctx context.Context, tx pgx.Tx, chapterID, seriesID string) (map[string]any, error) {
	objectRefs := make([]cleanupObjectRef, 0)
	rows, err := tx.Query(ctx, `
		SELECT image_path, responsive_image_path, media_generation
		FROM pages
		WHERE chapter_id=$1::uuid
		ORDER BY page_number`, chapterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var primary string
		var responsive *string
		var mediaGeneration int64
		if err := rows.Scan(&primary, &responsive, &mediaGeneration); err != nil {
			return nil, err
		}
		objectRefs = appendCleanupObjectRef(objectRefs, primary, mediaGeneration, "page-primary")
		if responsive != nil {
			objectRefs = appendCleanupObjectRef(objectRefs, *responsive, mediaGeneration, "page-responsive")
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return map[string]any{
		"schema_version": 2,
		"series_id":      seriesID,
		"chapter_ids":    []string{chapterID},
		"object_refs":    objectRefs,
		"image_paths":    cleanupObjectPaths(objectRefs),
		"reason":         "catalog-publication-replacement",
	}, nil
}

func validatePublicationCommandStoreBoundary(command model.PublicationCommand) error {
	if command.SchemaVersion != 1 || strings.TrimSpace(command.IdempotencyKey) == "" ||
		strings.TrimSpace(command.OperationID) == "" || strings.TrimSpace(command.ActorID) == "" ||
		strings.TrimSpace(command.MediaOperationID) == "" || command.SourceRevision < 1 ||
		command.MediaGeneration < 1 || command.IngestionGeneration < 1 ||
		strings.TrimSpace(command.PayloadSHA256) == "" || strings.TrimSpace(command.ManifestSHA256) == "" {
		return ErrConflict
	}
	if command.Manifest.SeriesID == "" || command.Manifest.SeriesSlug == "" || command.Manifest.ChapterSlug == "" || len(command.Manifest.Pages) == 0 {
		return ErrConflict
	}
	if command.ChapterID == nil && command.ExpectedRevision != 0 {
		return ErrStaleCatalogRevision
	}
	if command.ChapterID != nil && command.ExpectedRevision < 1 {
		return ErrStaleCatalogRevision
	}
	for index, page := range command.Manifest.Pages {
		if page.PageNumber != index+1 || page.EncodingVersion != 4 || page.ImagePath == "" || page.EncodingSeed == "" {
			return ErrConflict
		}
	}
	return nil
}

// CommitPublication is the short Catalog-owned production commit boundary.
// Conversion/upload and Media evidence creation happen before this transaction.
// The transaction serializes the idempotency key, validates durable Media
// evidence and target revision, replaces chapter/pages, appends outbox/cleanup
// effects, records the receipt, and only then commits.
func (s *Store) CommitPublication(ctx context.Context, command model.PublicationCommand) (model.CatalogMutationReceipt, error) {
	manifestDigest, _, err := model.ValidatePublicationCommand(command)
	if err != nil {
		return model.CatalogMutationReceipt{}, ErrConflict
	}
	command.ManifestSHA256 = manifestDigest
	if err := validatePublicationCommandStoreBoundary(command); err != nil {
		return model.CatalogMutationReceipt{}, err
	}

	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	defer tx.Rollback(ctx)

	// Prevent two first deliveries of the same missing receipt from both doing
	// production work before the receipt primary-key conflict becomes visible.
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, command.IdempotencyKey); err != nil {
		return model.CatalogMutationReceipt{}, err
	}

	existing, found, err := publicationReceiptTx(ctx, tx, command.IdempotencyKey)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	if found {
		if existing.PayloadSHA256 != command.PayloadSHA256 || existing.OperationID != command.OperationID || existing.ActorID != command.ActorID {
			return model.CatalogMutationReceipt{}, ErrIdempotencyConflict
		}
		actorAuthorized, err := publicationActorAuthorizedTx(ctx, tx, command.ActorID)
		if err != nil {
			return model.CatalogMutationReceipt{}, err
		}
		if !actorAuthorized {
			return model.CatalogMutationReceipt{}, ErrPublicationActorUnauthorized
		}
		return existing, nil
	}

	if err := lockPublicationIngestionOperationTx(ctx, tx, command.OperationID); err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	authority, err := publicationIngestionAuthorityTx(ctx, tx, command.OperationID)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	if err := validatePublicationIngestionAuthority(command, authority); err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	actorAuthorized, err := publicationActorAuthorizedTx(ctx, tx, command.ActorID)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	if !actorAuthorized {
		return model.CatalogMutationReceipt{}, ErrPublicationActorUnauthorized
	}

	evidence, err := publicationEvidenceTx(ctx, tx, command.MediaOperationID)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	if err := validatePublicationEvidence(command, evidence); err != nil {
		return model.CatalogMutationReceipt{}, err
	}

	var seriesSlug string
	var seriesRevision int64
	err = tx.QueryRow(ctx, `
		SELECT slug, catalog_revision
		FROM series
		WHERE id=$1::uuid
		FOR UPDATE`, command.Manifest.SeriesID,
	).Scan(&seriesSlug, &seriesRevision)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.CatalogMutationReceipt{}, ErrNotFound
	}
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	if seriesSlug != command.Manifest.SeriesSlug {
		return model.CatalogMutationReceipt{}, ErrConflict
	}

	chapterNumber, err := strconv.ParseFloat(command.ChapterNumber, 64)
	if err != nil {
		return model.CatalogMutationReceipt{}, ErrConflict
	}

	var chapterID string
	var chapterRevision int64
	isReplacement := command.ChapterID != nil
	if isReplacement {
		chapterID = *command.ChapterID
		var currentSeriesID string
		err = tx.QueryRow(ctx, `
			SELECT series_id::text, catalog_revision
			FROM chapters
			WHERE id=$1::uuid
			FOR UPDATE`, chapterID,
		).Scan(&currentSeriesID, &chapterRevision)
		if errors.Is(err, pgx.ErrNoRows) {
			return model.CatalogMutationReceipt{}, ErrNotFound
		}
		if err != nil {
			return model.CatalogMutationReceipt{}, err
		}
		if currentSeriesID != command.Manifest.SeriesID || chapterRevision != command.ExpectedRevision {
			return model.CatalogMutationReceipt{}, ErrStaleCatalogRevision
		}

		cleanup, err := publicationCleanupPayloadTx(ctx, tx, chapterID, command.Manifest.SeriesID)
		if err != nil {
			return model.CatalogMutationReceipt{}, err
		}
		if len(cleanup["image_paths"].([]string)) > 0 {
			if err := enqueueCleanupTx(ctx, tx, "chapter-replacement", chapterID, cleanup); err != nil {
				return model.CatalogMutationReceipt{}, err
			}
		}
		if _, err := tx.Exec(ctx, `DELETE FROM pages WHERE chapter_id=$1::uuid`, chapterID); err != nil {
			return model.CatalogMutationReceipt{}, err
		}
		chapterRevision++
		_, err = tx.Exec(ctx, `
			UPDATE chapters
			SET chapter_number=$2::numeric, title=$3, slug=$4, status='published',
			    page_count=$5, catalog_revision=$6, updated_at=NOW()
			WHERE id=$1::uuid`, chapterID, command.ChapterNumber, command.Title,
			command.Manifest.ChapterSlug, len(command.Manifest.Pages), chapterRevision)
		if err != nil {
			if isUniqueViolation(err) {
				return model.CatalogMutationReceipt{}, ErrConflict
			}
			return model.CatalogMutationReceipt{}, err
		}
	} else {
		chapterRevision = 1
		err = tx.QueryRow(ctx, `
			INSERT INTO chapters(
				series_id, chapter_number, title, slug, status, page_count, catalog_revision
			) VALUES($1::uuid,$2::numeric,$3,$4,'published',$5,1)
			RETURNING id::text`, command.Manifest.SeriesID, command.ChapterNumber,
			command.Title, command.Manifest.ChapterSlug, len(command.Manifest.Pages),
		).Scan(&chapterID)
		if err != nil {
			if isUniqueViolation(err) {
				return model.CatalogMutationReceipt{}, ErrConflict
			}
			return model.CatalogMutationReceipt{}, err
		}
	}

	for _, page := range command.Manifest.Pages {
		var responsivePath any
		var responsiveWidth any
		var responsiveHeight any
		if page.Responsive != nil {
			responsivePath = page.Responsive.ImagePath
			responsiveWidth = page.Responsive.Width
			responsiveHeight = page.Responsive.Height
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO pages(
				chapter_id,page_number,image_path,width,height,
				responsive_image_path,responsive_width,responsive_height,
				encoding_version,encoding_rows,encoding_columns,encoding_seed,media_generation
			) VALUES(
				$1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
			)`, chapterID, page.PageNumber, page.ImagePath, page.Width, page.Height,
			responsivePath, responsiveWidth, responsiveHeight, page.EncodingVersion,
			page.EncodingRows, page.EncodingColumns, page.EncodingSeed, command.MediaGeneration); err != nil {
			return model.CatalogMutationReceipt{}, err
		}
	}

	seriesRevision++
	var seriesUpdatedAt time.Time
	if err := tx.QueryRow(ctx, `
		UPDATE series
		SET catalog_revision=$2, updated_at=NOW()
		WHERE id=$1::uuid
		RETURNING updated_at`, command.Manifest.SeriesID, seriesRevision,
	).Scan(&seriesUpdatedAt); err != nil {
		return model.CatalogMutationReceipt{}, err
	}

	if _, err := enqueueSeriesUpdatedTx(ctx, tx, command.Manifest.SeriesID, seriesSlug,
		[]string{"chapters", "updated_at"}, seriesUpdatedAt, "catalog-publication-command", EventMetadata{
			RequestID: command.RequestID, OperationID: command.OperationID, Revision: seriesRevision,
		}); err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	publicationEventID, err := enqueueChapterPublishedTx(
		ctx, tx, chapterID, command.Manifest.SeriesID, chapterRevision, chapterNumber,
		command.Manifest.ChapterSlug, seriesSlug, command.Title,
		len(command.Manifest.Pages), seriesUpdatedAt, "catalog-publication-command", EventMetadata{
			RequestID: command.RequestID, OperationID: command.OperationID, Revision: chapterRevision,
		},
	)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}

	receipt := model.CatalogMutationReceipt{
		SchemaVersion:      1,
		Status:             "committed",
		IdempotencyKey:     command.IdempotencyKey,
		OperationID:        command.OperationID,
		ActorID:            command.ActorID,
		PayloadSHA256:      command.PayloadSHA256,
		SeriesID:           command.Manifest.SeriesID,
		ChapterID:          chapterID,
		ChapterRevision:    chapterRevision,
		SeriesRevision:     seriesRevision,
		PageCount:          len(command.Manifest.Pages),
		PublicationEventID: publicationEventID,
	}
	resultJSON, err := json.Marshal(receipt)
	if err != nil {
		return model.CatalogMutationReceipt{}, err
	}
	_, err = tx.Exec(ctx, `
		INSERT INTO catalog_mutation_receipts(
			idempotency_key,operation_id,actor_id,payload_sha256,series_id,chapter_id,
			chapter_revision,series_revision,page_count,publication_event_id,result
		) VALUES(
			$1::uuid,$2::uuid,$3::uuid,$4,$5::uuid,$6::uuid,$7,$8,$9,$10::uuid,$11::jsonb
		)`, receipt.IdempotencyKey, receipt.OperationID, receipt.ActorID, receipt.PayloadSHA256,
		receipt.SeriesID, receipt.ChapterID, receipt.ChapterRevision, receipt.SeriesRevision,
		receipt.PageCount, receipt.PublicationEventID, resultJSON)
	if err != nil {
		if isUniqueViolation(err) {
			return model.CatalogMutationReceipt{}, ErrIdempotencyConflict
		}
		return model.CatalogMutationReceipt{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.CatalogMutationReceipt{}, fmt.Errorf("commit catalog publication: %w", err)
	}
	return receipt, nil
}
