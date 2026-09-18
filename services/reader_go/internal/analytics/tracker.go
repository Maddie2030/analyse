package analytics

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

type event struct {
	seriesID string
	actorKey string
}

type Tracker struct {
	db            *pgxpool.Pool
	redis         *redis.Client
	log           *slog.Logger
	dedupeTTL     time.Duration
	retentionDays int
	queue         chan event
	wg            sync.WaitGroup
	cleanupCancel context.CancelFunc
}

func New(db *pgxpool.Pool, redisClient *redis.Client, log *slog.Logger, dedupeTTL time.Duration, queueSize, workers, retentionDays int) *Tracker {
	if queueSize < 1 {
		queueSize = 1024
	}
	if workers < 1 {
		workers = 1
	}
	if retentionDays < 31 {
		retentionDays = 45
	}
	if dedupeTTL <= 0 {
		dedupeTTL = 30 * time.Minute
	}

	t := &Tracker{
		db: db, redis: redisClient, log: log, dedupeTTL: dedupeTTL,
		retentionDays: retentionDays, queue: make(chan event, queueSize),
	}
	for i := 0; i < workers; i++ {
		t.wg.Add(1)
		go t.worker()
	}
	cleanupCtx, cancel := context.WithCancel(context.Background())
	t.cleanupCancel = cancel
	t.wg.Add(1)
	go t.cleanupLoop(cleanupCtx)
	return t
}

// Track is intentionally non-blocking. Trending analytics must never add latency
// or availability coupling to a successful reader manifest request.
func (t *Tracker) Track(seriesID, actorKey string) {
	if t == nil || strings.TrimSpace(seriesID) == "" || strings.TrimSpace(actorKey) == "" {
		return
	}
	select {
	case t.queue <- event{seriesID: seriesID, actorKey: actorKey}:
	default:
		t.log.Debug("trending analytics queue full; dropping non-critical signal", "series_id", seriesID)
	}
}

func (t *Tracker) worker() {
	defer t.wg.Done()
	for e := range t.queue {
		t.record(e)
	}
}

func (t *Tracker) record(e event) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	sum := sha256.Sum256([]byte(e.actorKey))
	actorHash := hex.EncodeToString(sum[:12])
	dedupeKey := "analytics:trend:dedupe:" + e.seriesID + ":" + actorHash
	fresh, err := t.redis.SetNX(ctx, dedupeKey, "1", t.dedupeTTL).Result()
	if err != nil {
		t.log.Warn("trending dedupe unavailable; skipping non-critical signal", "error", err, "series_id", e.seriesID)
		return
	}
	if !fresh {
		return
	}

	_, err = t.db.Exec(ctx, `
        INSERT INTO series_trending_hourly (series_id, bucket_start, open_count, updated_at)
        VALUES ($1::uuid, date_trunc('hour', NOW()), 1, NOW())
        ON CONFLICT (series_id, bucket_start)
        DO UPDATE SET open_count = series_trending_hourly.open_count + 1,
                      updated_at = NOW()
    `, e.seriesID)
	if err != nil {
		// Let a later reader open retry instead of suppressing the signal for the full TTL.
		_ = t.redis.Del(ctx, dedupeKey).Err()
		t.log.Warn("trending aggregate write failed; reader request remains successful", "error", err, "series_id", e.seriesID)
	}
}

func (t *Tracker) cleanupLoop(ctx context.Context) {
	defer t.wg.Done()
	t.cleanup(ctx)
	ticker := time.NewTicker(6 * time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			t.cleanup(ctx)
		}
	}
}

func (t *Tracker) cleanup(parent context.Context) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	if _, err := t.db.Exec(ctx, `DELETE FROM series_trending_hourly WHERE bucket_start < NOW() - ($1::int * INTERVAL '1 day')`, t.retentionDays); err != nil && ctx.Err() == nil {
		t.log.Warn("trending retention cleanup failed", "error", err)
	}
}

func (t *Tracker) Close(ctx context.Context) error {
	if t == nil {
		return nil
	}
	if t.cleanupCancel != nil {
		t.cleanupCancel()
	}
	close(t.queue)
	done := make(chan struct{})
	go func() { t.wg.Wait(); close(done) }()
	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
