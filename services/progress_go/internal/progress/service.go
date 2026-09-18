package progress

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
	"mreader/progress/internal/store"
)

type Service struct {
	redis           *redis.Client
	cacheRedis      *redis.Client
	store           *store.Store
	log             *slog.Logger
	stream          string
	group           string
	consumer        string
	flushBatch      int64
	reclaimMinIdle  time.Duration
	reclaimInterval time.Duration
}

type Value = store.CommandResult

func New(
	redisClient *redis.Client,
	cacheRedisClient *redis.Client,
	st *store.Store,
	log *slog.Logger,
	stream string,
	group string,
	consumer string,
	flushBatch int64,
	reclaimMinIdleSeconds int,
	reclaimIntervalSeconds int,
) *Service {
	return &Service{
		redis:           redisClient,
		cacheRedis:      cacheRedisClient,
		store:           st,
		log:             log,
		stream:          stream,
		group:           group,
		consumer:        consumer,
		flushBatch:      flushBatch,
		reclaimMinIdle:  positiveDuration(reclaimMinIdleSeconds, 30) * time.Second,
		reclaimInterval: positiveDuration(reclaimIntervalSeconds, 10) * time.Second,
	}
}

func cacheKey(userID, seriesID string) string {
	return "progress:" + userID + ":" + seriesID
}

// Personal reads always use primary PostgreSQL. Redis is only available to the
// explicitly enabled legacy drain, never an acknowledgement or reading authority.
func (s *Service) Get(ctx context.Context, userID, seriesID string) (*Value, error) {
	p, err := s.store.Get(ctx, userID, seriesID)
	if err != nil || p == nil {
		return nil, err
	}
	return &Value{Progress: *p, Accepted: true, Code: "accepted"}, nil
}

func (s *Service) RecordOpen(ctx context.Context, userID string, target store.Target, command store.OpenCommand) (Value, error) {
	return s.store.OpenReadingState(ctx, userID, target, command)
}

func (s *Service) Save(ctx context.Context, userID string, target store.Target, command store.CommitCommand) (Value, error) {
	return s.store.CommitReadingState(ctx, userID, target, command)
}

func (s *Service) RunFlusher(ctx context.Context) {
	err := s.redis.XGroupCreateMkStream(
		ctx,
		s.stream,
		s.group,
		"0",
	).Err()
	if err != nil && !stringsContains(err.Error(), "BUSYGROUP") {
		s.log.Error("progress stream group create failed", "error", err)
	}

	nextReclaim := time.Now()
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		if !time.Now().Before(nextReclaim) {
			if err := s.reclaimPending(ctx); err != nil && ctx.Err() == nil {
				s.log.Error("progress stale pending reclaim failed", "error", err)
			}
			nextReclaim = time.Now().Add(s.reclaimInterval)
		}

		streams, err := s.redis.XReadGroup(
			ctx,
			&redis.XReadGroupArgs{
				Group:    s.group,
				Consumer: s.consumer,
				Streams:  []string{s.stream, ">"},
				Count:    s.flushBatch,
				Block:    time.Second,
			},
		).Result()

		if errors.Is(err, redis.Nil) {
			continue
		}
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			s.log.Error("progress stream read failed", "error", err)
			time.Sleep(time.Second)
			continue
		}

		for _, stream := range streams {
			s.processMessages(ctx, stream.Messages, false)
		}
	}
}

func (s *Service) reclaimPending(ctx context.Context) error {
	start := "0-0"
	for {
		messages, nextStart, err := s.redis.XAutoClaim(
			ctx,
			&redis.XAutoClaimArgs{
				Stream:   s.stream,
				Group:    s.group,
				Consumer: s.consumer,
				MinIdle:  s.reclaimMinIdle,
				Start:    start,
				Count:    s.flushBatch,
			},
		).Result()
		if errors.Is(err, redis.Nil) {
			return nil
		}
		if err != nil {
			return err
		}

		if len(messages) > 0 {
			s.log.Info(
				"reclaimed stale progress messages",
				"count", len(messages),
				"min_idle_ms", s.reclaimMinIdle.Milliseconds(),
			)
			s.processMessages(ctx, messages, true)
		}

		if nextStart == "0-0" || nextStart == start {
			return nil
		}
		start = nextStart
	}
}

func (s *Service) processMessages(
	ctx context.Context,
	messages []redis.XMessage,
	reclaimed bool,
) {
	if len(messages) == 0 {
		return
	}

	type groupedUpdate struct {
		update store.ProgressUpdate
		ids    []string
	}
	groups := make(map[string]*groupedUpdate, len(messages))
	order := make([]string, 0, len(messages))
	ackPermanent := make([]string, 0)

	for _, msg := range messages {
		update, err := parseMessage(msg)
		if err != nil {
			// Stream messages are produced by this service; malformed values are
			// permanent poison data, not transient DB failures. Ack them once after
			// logging so one bad record cannot block the consumer group forever.
			s.log.Error(
				"discarding malformed progress stream message",
				"message_id", msg.ID,
				"reclaimed", reclaimed,
				"error", err,
			)
			ackPermanent = append(ackPermanent, msg.ID)
			continue
		}
		// Resume is one row per series, but exact read state is one row per chapter.
		// Coalescing across chapters would silently discard chapter_reads markers.
		key := update.UserID + "\x00" + update.SeriesID + "\x00" + update.ChapterID
		group := groups[key]
		if group == nil {
			groups[key] = &groupedUpdate{update: update, ids: []string{msg.ID}}
			order = append(order, key)
			continue
		}
		group.ids = append(group.ids, msg.ID)
		if update.UpdatedAt.After(group.update.UpdatedAt) ||
			(update.UpdatedAt.Equal(group.update.UpdatedAt) && msg.ID > group.update.SourceMessageID) {
			group.update = update
		}
	}

	if len(ackPermanent) > 0 {
		if err := s.redis.XAck(ctx, s.stream, s.group, ackPermanent...).Err(); err != nil {
			s.log.Warn("progress poison-message ack failed", "count", len(ackPermanent), "error", err)
		}
	}
	if len(order) == 0 {
		return
	}

	updates := make([]store.ProgressUpdate, 0, len(order))
	for _, key := range order {
		updates = append(updates, groups[key].update)
	}
	results, err := s.store.UpsertBatch(ctx, updates)
	if err != nil {
		s.log.Error(
			"progress batch persistence failed",
			"messages", len(messages),
			"chapter_coalesced_updates", len(updates),
			"reclaimed", reclaimed,
			"error", err,
		)
		return
	}

	ackIDs := make([]string, 0, len(messages))
	for i, key := range order {
		group := groups[key]
		result := results[i]
		if !result.Valid {
			_ = s.cacheRedis.Del(ctx, cacheKey(group.update.UserID, group.update.SeriesID)).Err()
			s.log.Info(
				"discarding stale progress for deleted target",
				"message_id", group.update.SourceMessageID,
				"series_id", group.update.SeriesID,
				"coalesced", len(group.ids),
				"reclaimed", reclaimed,
			)
		} else if !result.Applied {
			s.log.Debug(
				"progress persistence suppressed stale or duplicate delivery",
				"message_id", group.update.SourceMessageID,
				"coalesced", len(group.ids),
				"reclaimed", reclaimed,
			)
		}
		ackIDs = append(ackIDs, group.ids...)
	}

	if len(ackIDs) > 0 {
		if err := s.redis.XAck(ctx, s.stream, s.group, ackIDs...).Err(); err != nil {
			s.log.Warn(
				"progress stream batch ack failed",
				"count", len(ackIDs),
				"reclaimed", reclaimed,
				"error", err,
			)
		}
	}
}

func parseMessage(msg redis.XMessage) (store.ProgressUpdate, error) {
	userID := stringValue(msg.Values["user_id"])
	seriesID := stringValue(msg.Values["series_id"])
	chapterID := stringValue(msg.Values["chapter_id"])
	if userID == "" || seriesID == "" || chapterID == "" {
		return store.ProgressUpdate{}, errors.New("missing progress identifiers")
	}

	lastPage, err := strconv.Atoi(stringValue(msg.Values["last_page"]))
	if err != nil || lastPage < 1 {
		return store.ProgressUpdate{}, fmt.Errorf("invalid last_page: %v", err)
	}
	scrollPosition, err := strconv.ParseFloat(stringValue(msg.Values["scroll_position"]), 64)
	if err != nil || scrollPosition < 0 || scrollPosition > 1 {
		return store.ProgressUpdate{}, fmt.Errorf("invalid scroll_position: %v", err)
	}
	updatedAt, err := time.Parse(time.RFC3339Nano, stringValue(msg.Values["updated_at"]))
	if err != nil {
		return store.ProgressUpdate{}, fmt.Errorf("invalid updated_at: %w", err)
	}

	return store.ProgressUpdate{
		UserID: userID, SeriesID: seriesID, ChapterID: chapterID,
		LastPage: lastPage, ScrollPosition: scrollPosition,
		UpdatedAt: updatedAt, SourceMessageID: msg.ID,
	}, nil
}

func positiveDuration(value int, fallback int) time.Duration {
	if value <= 0 {
		value = fallback
	}
	return time.Duration(value)
}

func stringValue(value any) string {
	switch v := value.(type) {
	case string:
		return v
	case []byte:
		return string(v)
	default:
		return fmt.Sprint(v)
	}
}

func stringsContains(value, target string) bool {
	for i := 0; i+len(target) <= len(value); i++ {
		if value[i:i+len(target)] == target {
			return true
		}
	}
	return false
}
