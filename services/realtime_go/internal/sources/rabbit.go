package sources

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	amqp "github.com/rabbitmq/amqp091-go"
	"mreader/realtime/internal/hub"
)

type RabbitSource struct {
	url            string
	exchange       string
	reconnectDelay time.Duration
	db             *pgxpool.Pool
	hub            *hub.Hub
	log            *slog.Logger
	ready          atomic.Bool
	mu             sync.Mutex
	conn           *amqp.Connection
}

type eventEnvelope struct {
	EventID   string          `json:"event_id"`
	EventType string          `json:"event_type"`
	Payload   json.RawMessage `json:"payload"`
}

type notificationBatch struct {
	SourceEventID string `json:"source_event_id"`
}

type notificationSignal struct {
	Type         string              `json:"type"`
	Notification notificationPayload `json:"notification"`
	UnreadCount  int64               `json:"unread_count"`
}

type notificationPayload struct {
	ID        string  `json:"id"`
	Kind      string  `json:"kind"`
	Message   string  `json:"message"`
	SeriesID  *string `json:"series_id"`
	ChapterID *string `json:"chapter_id"`
	IsRead    bool    `json:"is_read"`
	CreatedAt string  `json:"created_at"`
}

func NewRabbitSource(url, exchange string, reconnectDelay time.Duration, db *pgxpool.Pool, h *hub.Hub, log *slog.Logger) *RabbitSource {
	return &RabbitSource{url: url, exchange: exchange, reconnectDelay: reconnectDelay, db: db, hub: h, log: log}
}

func (s *RabbitSource) Ready() bool { return s.ready.Load() }

func (s *RabbitSource) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ready.Store(false)
	if s.conn == nil {
		return nil
	}
	err := s.conn.Close()
	s.conn = nil
	return err
}

func (s *RabbitSource) Run(ctx context.Context) {
	for ctx.Err() == nil {
		if err := s.consumeOnce(ctx); err != nil && ctx.Err() == nil {
			s.log.Warn("realtime RabbitMQ source disconnected", "error", err)
		}
		s.ready.Store(false)
		if !sleepContext(ctx, s.reconnectDelay) {
			return
		}
	}
}

func (s *RabbitSource) consumeOnce(ctx context.Context) error {
	conn, err := amqp.DialConfig(s.url, amqp.Config{
		Heartbeat:  10 * time.Second,
		Locale:     "en_US",
		Properties: amqp.Table{"connection_name": "mreader-realtime"},
	})
	if err != nil {
		return fmt.Errorf("rabbitmq connect: %w", err)
	}
	s.mu.Lock()
	s.conn = conn
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		if s.conn == conn {
			s.conn = nil
		}
		s.mu.Unlock()
		_ = conn.Close()
	}()

	ch, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("rabbitmq channel: %w", err)
	}
	defer ch.Close()
	if err := ch.ExchangeDeclare(s.exchange, "topic", true, false, false, false, nil); err != nil {
		return fmt.Errorf("events exchange: %w", err)
	}
	queue, err := ch.QueueDeclare("", false, true, true, false, nil)
	if err != nil {
		return fmt.Errorf("realtime ephemeral queue: %w", err)
	}
	if err := ch.QueueBind(queue.Name, "notification.batch.created", s.exchange, false, nil); err != nil {
		return fmt.Errorf("realtime notification binding: %w", err)
	}
	if err := ch.Qos(32, 0, false); err != nil {
		return fmt.Errorf("realtime qos: %w", err)
	}
	deliveries, err := ch.Consume(queue.Name, "mreader-realtime", false, true, false, false, nil)
	if err != nil {
		return fmt.Errorf("realtime consume: %w", err)
	}
	s.ready.Store(true)
	s.log.Info("realtime RabbitMQ source ready", "queue", queue.Name)

	for {
		select {
		case <-ctx.Done():
			return nil
		case delivery, ok := <-deliveries:
			if !ok {
				return fmt.Errorf("realtime RabbitMQ delivery channel closed")
			}
			if err := s.processDelivery(ctx, delivery.Body); err != nil {
				// Realtime is an ephemeral acceleration layer, not canonical state.
				// Requeueing a poison or DB-failing live signal can create an
				// immediate hot loop on this exclusive queue. Drop the live signal
				// after logging; PostgreSQL remains canonical and the frontend's
				// HTTP refresh path recovers missed notification state.
				s.log.Error("realtime notification signal dropped", "error", err, "message_id", delivery.MessageId)
				if nackErr := delivery.Nack(false, false); nackErr != nil {
					return nackErr
				}
				continue
			}
			if err := delivery.Ack(false); err != nil {
				return err
			}
		}
	}
}

func (s *RabbitSource) processDelivery(ctx context.Context, body []byte) error {
	var envelope eventEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		return fmt.Errorf("decode realtime envelope: %w", err)
	}
	if envelope.EventType != "notification.batch.created" {
		return nil
	}
	var batch notificationBatch
	if err := json.Unmarshal(envelope.Payload, &batch); err != nil {
		return fmt.Errorf("decode notification batch: %w", err)
	}
	if batch.SourceEventID == "" {
		return fmt.Errorf("notification batch missing source_event_id")
	}

	rows, err := s.db.Query(
		ctx,
		`WITH batch_rows AS (
             SELECT n.id,n.user_id,n.series_id,n.chapter_id,n.kind,n.message,n.is_read,n.created_at
               FROM notifications n
              WHERE n.source_event_id=$1::uuid
           ),
           batch_users AS (
             SELECT DISTINCT user_id FROM batch_rows
           ),
           unread_counts AS (
             SELECT n.user_id, COUNT(*)::bigint AS unread_count
               FROM notifications n
               JOIN batch_users u ON u.user_id=n.user_id
              WHERE n.is_read=FALSE
              GROUP BY n.user_id
           )
           SELECT n.id::text,
                  n.user_id::text,
                  n.series_id::text,
                  n.chapter_id::text,
                  n.kind,
                  n.message,
                  n.is_read,
                  n.created_at,
                  COALESCE(u.unread_count,0)::bigint AS unread_count
             FROM batch_rows n
             LEFT JOIN unread_counts u ON u.user_id=n.user_id
            ORDER BY n.created_at,n.id`,
		batch.SourceEventID,
	)
	if err != nil {
		return err
	}
	defer rows.Close()

	for rows.Next() {
		var id, userID, kind, message string
		var seriesID, chapterID *string
		var isRead bool
		var createdAt time.Time
		var unreadCount int64
		if err := rows.Scan(&id, &userID, &seriesID, &chapterID, &kind, &message, &isRead, &createdAt, &unreadCount); err != nil {
			return err
		}
		s.hub.BroadcastUser(userID, notificationSignal{
			Type:        "notification.created",
			UnreadCount: unreadCount,
			Notification: notificationPayload{
				ID: id, Kind: kind, Message: message, SeriesID: seriesID, ChapterID: chapterID,
				IsRead: isRead, CreatedAt: createdAt.UTC().Format(time.RFC3339Nano),
			},
		})
	}
	return rows.Err()
}

func sleepContext(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}
