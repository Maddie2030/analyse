package store

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"mreader/catalog/internal/model"
)

func publicationTestPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := strings.TrimSpace(os.Getenv("MREADER_TEST_POSTGRES_DSN"))
	if dsn == "" {
		t.Skip("MREADER_TEST_POSTGRES_DSN is required for publication transaction tests")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		t.Fatal(err)
	}
	return pool
}

func publicationTestUUID(t *testing.T) string {
	t.Helper()
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		t.Fatal(err)
	}
	raw[6] = (raw[6] & 0x0f) | 0x40
	raw[8] = (raw[8] & 0x3f) | 0x80
	hexValue := hex.EncodeToString(raw[:])
	return fmt.Sprintf("%s-%s-%s-%s-%s",
		hexValue[0:8], hexValue[8:12], hexValue[12:16], hexValue[16:20], hexValue[20:32])
}

func publicationTestAssetVersion(seed string) string {
	sum := sha256.Sum256([]byte("mreader-v4-overlap-tilepack:" + seed))
	return hex.EncodeToString(sum[:])[:20]
}

func publicationTestCommand(t *testing.T, seriesID, seriesSlug string, chapterID *string, expected int64, seed string) model.PublicationCommand {
	t.Helper()
	chapterSlug := "chapter-one"
	version := publicationTestAssetVersion(seed)
	command := model.PublicationCommand{
		SchemaVersion:       1,
		IdempotencyKey:      publicationTestUUID(t),
		OperationID:         publicationTestUUID(t),
		ActorID:             publicationTestUUID(t),
		SourceRevision:      1,
		IngestionGeneration: 1,
		MediaOperationID:    publicationTestUUID(t),
		MediaGeneration:     1,
		ChapterID:           chapterID,
		ExpectedRevision:    expected,
		ChapterNumber:       "1.00",
		Manifest: model.PublicationManifest{
			SchemaVersion: 1,
			SeriesID:      seriesID,
			SeriesSlug:    seriesSlug,
			ChapterSlug:   chapterSlug,
			Pages: []model.PublicationPage{{
				PublicationAsset: model.PublicationAsset{
					ImagePath: fmt.Sprintf("%s/%s/_v4/%s/0001.mrt", seriesSlug, chapterSlug, version),
					Width:     1080, Height: 1600, SizeBytes: 180000,
					SHA256: strings.Repeat("a", 64),
				},
				PageNumber: 1, EncodingVersion: 4, EncodingRows: 4, EncodingColumns: 4,
				EncodingSeed: seed,
			}},
		},
	}
	manifestDigest, payloadDigest, err := model.PublicationCommandDigests(command)
	if err != nil {
		t.Fatal(err)
	}
	command.ManifestSHA256 = manifestDigest
	command.PayloadSHA256 = payloadDigest
	return command
}

func publicationTestFixture(t *testing.T, pool *pgxpool.Pool, command model.PublicationCommand) {
	t.Helper()
	ctx := context.Background()
	actorKey := strings.ReplaceAll(command.ActorID, "-", "")
	if _, err := pool.Exec(ctx, `
		INSERT INTO users(id,username,email,password_hash,role,is_active)
		VALUES($1::uuid,$2,$3,'publication-test','admin',true)
		ON CONFLICT(id) DO UPDATE SET role='admin', is_active=true`,
		command.ActorID, "pub_"+actorKey[:16], "pub_"+actorKey[:16]+"@example.invalid"); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO ingestion_operations(
			id,source_kind,requesting_actor_id,status,phase,source_revision,revision,lease_generation
		) VALUES($1::uuid,'manual_upload',$2::uuid,'running','publishing',$3,1,$4)
		ON CONFLICT(id) DO UPDATE SET
			requesting_actor_id=EXCLUDED.requesting_actor_id,
			status='running', phase='publishing', source_revision=EXCLUDED.source_revision,
			lease_generation=EXCLUDED.lease_generation, cancel_requested_at=NULL`,
		command.OperationID, command.ActorID, command.SourceRevision, command.IngestionGeneration); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO series(id,title,slug,status,catalog_revision)
		VALUES($1::uuid,'publication test',$2,'ongoing',1)
		ON CONFLICT(id) DO NOTHING`, command.Manifest.SeriesID, command.Manifest.SeriesSlug); err != nil {
		t.Fatal(err)
	}
	evidence := fmt.Sprintf(
		`{"schema_version":1,"status":"completed","media_operation_id":%q,"operation_id":%q,"actor_id":%q,"source_revision":%d,"media_generation":%d,"page_count":%d,"manifest_sha256":%q}`,
		command.MediaOperationID, command.OperationID, command.ActorID, command.SourceRevision,
		command.MediaGeneration, len(command.Manifest.Pages), command.ManifestSHA256,
	)
	if _, err := pool.Exec(ctx, `
		INSERT INTO media_operations(
			operation_id,job_type,status,series_id,series_slug,event_partition_key,
			staged_object_path,metadata,output_paths,media_generation,
			publication_operation_id,publication_actor_id,source_revision,
			manifest_sha256,publication_page_count,completion_evidence,completed_at
		) VALUES(
			$1::uuid,'chapter-ingestion','completed',$2::uuid,$3,$2::text,
			'_tests/publication', '{}'::jsonb, '[]'::jsonb, $4,
			$5::uuid,$6::uuid,$7,$8,$9,$10::jsonb,NOW()
		)`, command.MediaOperationID, command.Manifest.SeriesID, command.Manifest.SeriesSlug,
		command.MediaGeneration, command.OperationID, command.ActorID, command.SourceRevision,
		command.ManifestSHA256, len(command.Manifest.Pages), evidence); err != nil {
		t.Fatal(err)
	}
}

func publicationTestCleanup(t *testing.T, pool *pgxpool.Pool, seriesID string) {
	t.Helper()
	ctx := context.Background()
	if _, err := pool.Exec(ctx, `
		DELETE FROM ingestion_operations
		WHERE id IN (
			SELECT publication_operation_id FROM media_operations
			WHERE series_id=$1::uuid AND publication_operation_id IS NOT NULL
		)`, seriesID); err != nil {
		t.Errorf("cleanup ingestion operations: %v", err)
	}
	if _, err := pool.Exec(ctx, `
		DELETE FROM users
		WHERE id IN (
			SELECT publication_actor_id FROM media_operations
			WHERE series_id=$1::uuid AND publication_actor_id IS NOT NULL
		)`, seriesID); err != nil {
		t.Errorf("cleanup publication actors: %v", err)
	}
	if _, err := pool.Exec(ctx, `DELETE FROM catalog_mutation_receipts WHERE series_id=$1::uuid`, seriesID); err != nil {
		t.Errorf("cleanup receipts: %v", err)
	}
	if _, err := pool.Exec(ctx, `DELETE FROM media_operations WHERE series_id=$1::uuid`, seriesID); err != nil {
		t.Errorf("cleanup media operations: %v", err)
	}
	if _, err := pool.Exec(ctx, `DELETE FROM series WHERE id=$1::uuid`, seriesID); err != nil {
		t.Errorf("cleanup series: %v", err)
	}
}

func publicationTestPrepared(t *testing.T, seed string) (*pgxpool.Pool, model.PublicationCommand, *Store, context.Context) {
	t.Helper()
	pool := publicationTestPool(t)
	t.Cleanup(pool.Close)
	seriesID := publicationTestUUID(t)
	seriesSlug := "publication-" + strings.ReplaceAll(seriesID[:8], "-", "")
	command := publicationTestCommand(t, seriesID, seriesSlug, nil, 0, seed)
	publicationTestFixture(t, pool, command)
	t.Cleanup(func() { publicationTestCleanup(t, pool, seriesID) })
	return pool, command, New(pool), context.Background()
}

func publicationTestCommitted(t *testing.T, seed string) (*pgxpool.Pool, model.PublicationCommand, *Store, context.Context, model.CatalogMutationReceipt) {
	t.Helper()
	pool, command, store, ctx := publicationTestPrepared(t, seed)
	receipt, err := store.CommitPublication(ctx, command)
	if err != nil {
		t.Fatal(err)
	}
	return pool, command, store, ctx, receipt
}

func TestCommitPublicationReceiptReplayAfterResponseLoss(t *testing.T) {
	pool, command, store, ctx, first := publicationTestCommitted(t, "0123456789abcdef0123456789abcdef")
	second, err := store.CommitPublication(ctx, command)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatalf("receipt replay changed result: first=%+v second=%+v", first, second)
	}

	var receipts, publishedEvents int
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM catalog_mutation_receipts WHERE idempotency_key=$1::uuid`, command.IdempotencyKey).Scan(&receipts); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, `SELECT count(*) FROM event_outbox WHERE event_id=$1::uuid AND event_type='chapter.published'`, first.PublicationEventID).Scan(&publishedEvents); err != nil {
		t.Fatal(err)
	}
	if receipts != 1 || publishedEvents != 1 {
		t.Fatalf("expected one receipt/event, got receipts=%d events=%d", receipts, publishedEvents)
	}
}

func TestCommitPublicationReceiptReplayRequiresCurrentAdminAuthorization(t *testing.T) {
	pool, command, store, ctx, _ := publicationTestCommitted(t, "8123456789abcdef0123456789abcdef")
	if _, err := pool.Exec(ctx, `UPDATE users SET is_active=false WHERE id=$1::uuid`, command.ActorID); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrPublicationActorUnauthorized) {
		t.Fatalf("expected replay to recheck current admin authorization, got %v", err)
	}
}

func TestCommitPublicationSameKeyDifferentBodyConflicts(t *testing.T) {
	_, command, store, ctx, _ := publicationTestCommitted(t, "0123456789abcdef0123456789abcdef")
	title := "different body"
	conflict := command
	conflict.Title = &title
	_, digest, err := model.PublicationCommandDigests(conflict)
	if err != nil {
		t.Fatal(err)
	}
	conflict.PayloadSHA256 = digest
	if _, err := store.CommitPublication(ctx, conflict); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("expected idempotency conflict, got %v", err)
	}
}

func TestCommitPublicationConcurrentStaleReplacementHasOneWinner(t *testing.T) {
	pool := publicationTestPool(t)
	defer pool.Close()
	seriesID := publicationTestUUID(t)
	seriesSlug := "publication-" + strings.ReplaceAll(seriesID[:8], "-", "")
	create := publicationTestCommand(t, seriesID, seriesSlug, nil, 0, "0123456789abcdef0123456789abcdef")
	publicationTestFixture(t, pool, create)
	defer publicationTestCleanup(t, pool, seriesID)
	store := New(pool)
	created, err := store.CommitPublication(context.Background(), create)
	if err != nil {
		t.Fatal(err)
	}

	chapterID := created.ChapterID
	left := publicationTestCommand(t, seriesID, seriesSlug, &chapterID, 1, "1123456789abcdef0123456789abcdef")
	right := publicationTestCommand(t, seriesID, seriesSlug, &chapterID, 1, "2123456789abcdef0123456789abcdef")
	publicationTestFixture(t, pool, left)
	publicationTestFixture(t, pool, right)

	errs := make(chan error, 2)
	var wg sync.WaitGroup
	for _, command := range []model.PublicationCommand{left, right} {
		command := command
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := store.CommitPublication(context.Background(), command)
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	var success, stale int
	for err := range errs {
		switch {
		case err == nil:
			success++
		case errors.Is(err, ErrStaleCatalogRevision):
			stale++
		default:
			t.Fatalf("unexpected concurrent result: %v", err)
		}
	}
	if success != 1 || stale != 1 {
		t.Fatalf("expected one commit and one stale revision, got success=%d stale=%d", success, stale)
	}

	var revision int64
	var receiptCount int
	if err := pool.QueryRow(context.Background(), `SELECT catalog_revision FROM chapters WHERE id=$1::uuid`, chapterID).Scan(&revision); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(context.Background(), `SELECT count(*) FROM catalog_mutation_receipts WHERE series_id=$1::uuid`, seriesID).Scan(&receiptCount); err != nil {
		t.Fatal(err)
	}
	if revision != 2 || receiptCount != 2 {
		t.Fatalf("unexpected authoritative result revision=%d receipts=%d", revision, receiptCount)
	}
}

func TestCommitPublicationRejectsCancelledOrStaleIngestionAuthority(t *testing.T) {
	pool := publicationTestPool(t)
	defer pool.Close()
	seriesID := publicationTestUUID(t)
	seriesSlug := "publication-" + strings.ReplaceAll(seriesID[:8], "-", "")
	command := publicationTestCommand(t, seriesID, seriesSlug, nil, 0, "3123456789abcdef0123456789abcdef")
	publicationTestFixture(t, pool, command)
	defer publicationTestCleanup(t, pool, seriesID)
	store := New(pool)
	ctx := context.Background()

	if _, err := pool.Exec(ctx, `UPDATE ingestion_operations SET status='cancel_requested',cancel_requested_at=NOW() WHERE id=$1::uuid`, command.OperationID); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrIngestionCancelled) {
		t.Fatalf("expected cancellation fence, got %v", err)
	}

	if _, err := pool.Exec(ctx, `UPDATE ingestion_operations SET status='running',cancel_requested_at=NULL,source_revision=$2 WHERE id=$1::uuid`, command.OperationID, command.SourceRevision+1); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrStaleIngestionSourceRevision) {
		t.Fatalf("expected stale source revision, got %v", err)
	}

	if _, err := pool.Exec(ctx, `UPDATE ingestion_operations SET source_revision=$2,lease_generation=$3 WHERE id=$1::uuid`, command.OperationID, command.SourceRevision, command.IngestionGeneration+1); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrStaleIngestionGeneration) {
		t.Fatalf("expected stale ingestion generation, got %v", err)
	}
}

func TestCommitPublicationRejectsInactiveOrNonAdminActor(t *testing.T) {
	pool, command, store, ctx := publicationTestPrepared(t, "4123456789abcdef0123456789abcdef")

	if _, err := pool.Exec(ctx, `UPDATE users SET is_active=false WHERE id=$1::uuid`, command.ActorID); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrPublicationActorUnauthorized) {
		t.Fatalf("expected inactive actor rejection, got %v", err)
	}

	if _, err := pool.Exec(ctx, `UPDATE users SET is_active=true,role='user' WHERE id=$1::uuid`, command.ActorID); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CommitPublication(ctx, command); !errors.Is(err, ErrPublicationActorUnauthorized) {
		t.Fatalf("expected non-admin actor rejection, got %v", err)
	}
}

func TestCommitPublicationConcurrentCreateHasOneAuthoritativeWinner(t *testing.T) {
	pool := publicationTestPool(t)
	defer pool.Close()
	seriesID := publicationTestUUID(t)
	seriesSlug := "publication-" + strings.ReplaceAll(seriesID[:8], "-", "")
	left := publicationTestCommand(t, seriesID, seriesSlug, nil, 0, "5123456789abcdef0123456789abcdef")
	right := publicationTestCommand(t, seriesID, seriesSlug, nil, 0, "6123456789abcdef0123456789abcdef")
	publicationTestFixture(t, pool, left)
	publicationTestFixture(t, pool, right)
	defer publicationTestCleanup(t, pool, seriesID)
	store := New(pool)

	errs := make(chan error, 2)
	var wg sync.WaitGroup
	for _, command := range []model.PublicationCommand{left, right} {
		command := command
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := store.CommitPublication(context.Background(), command)
			errs <- err
		}()
	}
	wg.Wait()
	close(errs)
	var success, conflict int
	for err := range errs {
		switch {
		case err == nil:
			success++
		case errors.Is(err, ErrConflict):
			conflict++
		default:
			t.Fatalf("unexpected concurrent-create result: %v", err)
		}
	}
	if success != 1 || conflict != 1 {
		t.Fatalf("expected one authoritative create and one conflict, got success=%d conflict=%d", success, conflict)
	}

	var chapters, receipts int
	if err := pool.QueryRow(context.Background(), `SELECT count(*) FROM chapters WHERE series_id=$1::uuid AND chapter_number=1.00`, seriesID).Scan(&chapters); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(context.Background(), `SELECT count(*) FROM catalog_mutation_receipts WHERE series_id=$1::uuid`, seriesID).Scan(&receipts); err != nil {
		t.Fatal(err)
	}
	if chapters != 1 || receipts != 1 {
		t.Fatalf("unexpected concurrent-create result chapters=%d receipts=%d", chapters, receipts)
	}
}
func TestMediaCompletionEvidenceIsDatabaseImmutable(t *testing.T) {
	pool, command, _, ctx := publicationTestPrepared(t, "7123456789abcdef0123456789abcdef")

	if _, err := pool.Exec(ctx, `
		UPDATE media_operations
		SET manifest_sha256=$2
		WHERE operation_id=$1::uuid`, command.MediaOperationID, strings.Repeat("b", 64)); err == nil {
		t.Fatal("expected sealed media completion evidence to reject manifest mutation")
	}

	if _, err := pool.Exec(ctx, `
		UPDATE media_operations
		SET last_queue_error='diagnostic-only'
		WHERE operation_id=$1::uuid`, command.MediaOperationID); err != nil {
		t.Fatalf("unrelated media diagnostic update should remain allowed: %v", err)
	}
}
