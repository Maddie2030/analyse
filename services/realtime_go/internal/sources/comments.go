package sources

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
	"mreader/realtime/internal/hub"
)

type CommentSource struct {
	redis *redis.Client
	hub   *hub.Hub
	log   *slog.Logger
	ready atomic.Bool
}

func NewCommentSource(redisClient *redis.Client, h *hub.Hub, log *slog.Logger) *CommentSource {
	return &CommentSource{redis: redisClient, hub: h, log: log}
}

func (s *CommentSource) Ready() bool { return s.ready.Load() }

func (s *CommentSource) Run(ctx context.Context) {
	for ctx.Err() == nil {
		if err := s.runOnce(ctx); err != nil && ctx.Err() == nil {
			s.log.Warn("realtime comment pubsub disconnected", "error", err)
		}
		s.ready.Store(false)
		if !sleepContext(ctx, 2*time.Second) {
			return
		}
	}
}

func (s *CommentSource) runOnce(ctx context.Context) error {
	pubsub := s.redis.PSubscribe(ctx, "social:comments:*")
	defer pubsub.Close()
	if _, err := pubsub.Receive(ctx); err != nil {
		return fmt.Errorf("subscribe comment pubsub: %w", err)
	}
	s.ready.Store(true)
	defer s.ready.Store(false)
	s.log.Info("realtime comment pubsub ready")

	channel := pubsub.Channel()
	for {
		select {
		case <-ctx.Done():
			return nil
		case message, ok := <-channel:
			if !ok {
				return fmt.Errorf("comment pubsub channel closed")
			}
			if err := s.forward(message.Channel, message.Payload); err != nil {
				s.log.Warn("realtime comment signal ignored", "error", err)
			}
		}
	}
}

func (s *CommentSource) forward(channel, raw string) error {
	rest := strings.TrimPrefix(channel, "social:comments:")
	parts := strings.Split(rest, ":")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return fmt.Errorf("invalid comment channel %q", channel)
	}
	var payload any
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return err
	}
	chapterID := any(parts[1])
	if parts[1] == "series" {
		chapterID = nil
	}
	s.hub.BroadcastComment(commentKey(parts[0], parts[1]), map[string]any{
		"type":       "comment.changed",
		"series_id":  parts[0],
		"chapter_id": chapterID,
		"event":      payload,
	})
	return nil
}

func commentKey(seriesID, chapterID string) string {
	return seriesID + ":" + chapterID
}
