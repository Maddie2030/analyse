package store

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"mreader/notification-worker/internal/events"
)

type chapterPublishedPostgresFixture struct {
	store       *Store
	pool        *pgxpool.Pool
	userID      string
	seriesID    string
	chapterID   string
	publishedAt time.Time
}

func notificationPostgresTestPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn, ok := os.LookupEnv("MREADER_TEST_POSTGRES_DSN")
	if !ok || strings.TrimSpace(dsn) == "" {
		t.Skip("MREADER_TEST_POSTGRES_DSN is required for notification PostgreSQL tests")
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatalf("parse notification PostgreSQL test DSN: %v", err)
	}
	config.MaxConns = 4
	config.MinConns = 0
	pool, err := pgxpool.NewWithConfig(context.Background(), config)
	if err != nil {
		t.Fatalf("open notification PostgreSQL test pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func notificationPostgresTestUUID(t *testing.T, pool *pgxpool.Pool) string {
	t.Helper()
	var value string
	if err := pool.QueryRow(context.Background(), `SELECT gen_random_uuid()::text`).Scan(&value); err != nil {
		t.Fatal(err)
	}
	return value
}

func newChapterPublishedPostgresFixture(t *testing.T, pool *pgxpool.Pool) chapterPublishedPostgresFixture {
	t.Helper()
	ctx := context.Background()
	userID := notificationPostgresTestUUID(t, pool)
	seriesID := notificationPostgresTestUUID(t, pool)
	chapterID := notificationPostgresTestUUID(t, pool)
	key := strings.ReplaceAll(seriesID, "-", "")[:16]
	publishedAt := time.Now().UTC().Add(time.Minute)

	if _, err := pool.Exec(ctx, `
		INSERT INTO users(id,username,email,password_hash,role,is_active)
		VALUES($1::uuid,$2,$3,'notification-test','user',true)`,
		userID, "notify_"+key, "notify_"+key+"@example.invalid"); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO series(id,title,slug,status)
		VALUES($1::uuid,$2,$3,'ongoing')`,
		seriesID, "Notification test "+key, "notification-"+key); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO chapters(id,series_id,chapter_number,title,slug,status,page_count)
		VALUES($1::uuid,$2::uuid,1.00,'Chapter 1','chapter-1','published',1)`,
		chapterID, seriesID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO subscriptions(user_id,series_id,created_at)
		VALUES($1::uuid,$2::uuid,$3::timestamptz)`,
		userID, seriesID, publishedAt.Add(-time.Minute)); err != nil {
		t.Fatal(err)
	}

	return chapterPublishedPostgresFixture{
		store:       New(pool),
		pool:        pool,
		userID:      userID,
		seriesID:    seriesID,
		chapterID:   chapterID,
		publishedAt: publishedAt,
	}
}

func (f chapterPublishedPostgresFixture) process(t *testing.T, eventVersion int, chapterRevision int64) ProcessResult {
	t.Helper()
	payload := events.ChapterPublished{
		ChapterID:       f.chapterID,
		SeriesID:        f.seriesID,
		ChapterRevision: chapterRevision,
		ChapterNumber:   1,
		ChapterSlug:     "chapter-1",
		SeriesSlug:      "notification-test",
		PageCount:       1,
		PublishedAt:     f.publishedAt,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	eventID := notificationPostgresTestUUID(t, f.pool)
	result, err := f.store.Process(context.Background(), events.Envelope{
		EventID:       eventID,
		EventType:     "chapter.published",
		EventVersion:  eventVersion,
		AggregateType: "chapter",
		AggregateID:   f.chapterID,
		OccurredAt:    time.Now().UTC(),
		Producer:      "notification-postgres-test",
		Payload:       raw,
	})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func (f chapterPublishedPostgresFixture) notificationCountForKey(t *testing.T, key string) int {
	t.Helper()
	var count int
	if err := f.pool.QueryRow(context.Background(), `
		SELECT count(*)
		FROM notifications
		WHERE user_id=$1::uuid AND chapter_id=$2::uuid AND kind='chapter.published' AND dedupe_key=$3`,
		f.userID, f.chapterID, key).Scan(&count); err != nil {
		t.Fatal(err)
	}
	return count
}

func TestChapterPublishedV2DedupeIsPublicationRevisionScoped(t *testing.T) {
	pool := notificationPostgresTestPool(t)

	v2 := newChapterPublishedPostgresFixture(t, pool)
	first := v2.process(t, 2, 1)
	if first.Inserted != 1 || first.Duplicate {
		t.Fatalf("revision 1 first delivery inserted=%d duplicate=%v", first.Inserted, first.Duplicate)
	}
	retry := v2.process(t, 2, 1)
	if retry.Inserted != 0 || retry.Duplicate {
		t.Fatalf("revision 1 different-event retry inserted=%d duplicate=%v", retry.Inserted, retry.Duplicate)
	}
	second := v2.process(t, 2, 2)
	if second.Inserted != 1 || second.Duplicate {
		t.Fatalf("revision 2 delivery inserted=%d duplicate=%v", second.Inserted, second.Duplicate)
	}

	for revision := int64(1); revision <= 2; revision++ {
		key := fmt.Sprintf("chapter.published:%s:revision:%d", v2.chapterID, revision)
		if count := v2.notificationCountForKey(t, key); count != 1 {
			t.Fatalf("revision %d notification count=%d want=1", revision, count)
		}
	}

	legacy := newChapterPublishedPostgresFixture(t, pool)
	legacyFirst := legacy.process(t, 1, 0)
	if legacyFirst.Inserted != 1 || legacyFirst.Duplicate {
		t.Fatalf("legacy v1 first delivery inserted=%d duplicate=%v", legacyFirst.Inserted, legacyFirst.Duplicate)
	}
	legacyRetry := legacy.process(t, 1, 0)
	if legacyRetry.Inserted != 0 || legacyRetry.Duplicate {
		t.Fatalf("legacy v1 different-event retry inserted=%d duplicate=%v", legacyRetry.Inserted, legacyRetry.Duplicate)
	}
	legacyKey := "chapter.published:" + legacy.chapterID
	if count := legacy.notificationCountForKey(t, legacyKey); count != 1 {
		t.Fatalf("legacy v1 notification count=%d want=1", count)
	}
}
