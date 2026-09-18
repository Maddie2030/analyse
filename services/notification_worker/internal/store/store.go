package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"mreader/notification-worker/internal/events"
)

type Store struct {
	db *pgxpool.Pool
}

type ProcessResult struct {
	Duplicate bool
	Inserted  int64
}

func New(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

func (s *Store) Ping(ctx context.Context) error {
	return s.db.Ping(ctx)
}

func (s *Store) Process(ctx context.Context, envelope events.Envelope) (ProcessResult, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ProcessResult{}, err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()

	var claimed string
	err = tx.QueryRow(
		ctx,
		`INSERT INTO notification_event_receipts(event_id,event_type,occurred_at)
         VALUES ($1::uuid,$2,$3)
         ON CONFLICT (event_id) DO NOTHING
         RETURNING event_id::text`,
		envelope.EventID,
		envelope.EventType,
		envelope.OccurredAt,
	).Scan(&claimed)
	if errors.Is(err, pgx.ErrNoRows) {
		if err := tx.Commit(ctx); err != nil {
			return ProcessResult{}, err
		}
		return ProcessResult{Duplicate: true}, nil
	}
	if err != nil {
		return ProcessResult{}, fmt.Errorf("claim notification event receipt: %w", err)
	}

	var inserted int64
	var partitionKey string
	var realtimePayload map[string]any

	switch envelope.EventType {
	case "chapter.published":
		payload, err := events.DecodeChapterPublished(envelope.Payload, envelope.EventVersion)
		if err != nil {
			return ProcessResult{}, err
		}
		dedupeKey, err := events.ChapterPublishedDedupeKey(envelope.EventVersion, payload)
		if err != nil {
			return ProcessResult{}, err
		}
		inserted, err = insertChapterNotifications(ctx, tx, envelope.EventID, dedupeKey, payload)
		if err != nil {
			return ProcessResult{}, err
		}
		partitionKey = payload.SeriesID
		realtimePayload = map[string]any{
			"source_event_id":    envelope.EventID,
			"notification_count": inserted,
			"series_id":          payload.SeriesID,
			"chapter_id":         payload.ChapterID,
			"recipient_user_id":  nil,
			"created_at":         time.Now().UTC().Format(time.RFC3339Nano),
		}

	case "notification.requested":
		payload, err := events.DecodeNotificationRequested(envelope.Payload)
		if err != nil {
			return ProcessResult{}, err
		}
		inserted, err = insertRequestedNotification(ctx, tx, envelope.EventID, payload)
		if err != nil {
			return ProcessResult{}, err
		}
		partitionKey = payload.RecipientUserID
		realtimePayload = map[string]any{
			"source_event_id":    envelope.EventID,
			"notification_count": inserted,
			"series_id":          nullableString(payload.SeriesID),
			"chapter_id":         nullableString(payload.ChapterID),
			"recipient_user_id":  payload.RecipientUserID,
			"created_at":         time.Now().UTC().Format(time.RFC3339Nano),
		}

	default:
		return ProcessResult{}, fmt.Errorf("unsupported notification event type %q", envelope.EventType)
	}

	if inserted > 0 {
		if err := enqueueRealtimeBatch(ctx, tx, envelope.EventID, partitionKey, realtimePayload); err != nil {
			return ProcessResult{}, err
		}
	}

	if _, err := tx.Exec(
		ctx,
		`UPDATE notification_event_receipts
            SET notifications_inserted=$2,
                processed_at=NOW()
          WHERE event_id=$1::uuid`,
		envelope.EventID,
		inserted,
	); err != nil {
		return ProcessResult{}, fmt.Errorf("update notification event receipt: %w", err)
	}

	if err := tx.Commit(ctx); err != nil {
		return ProcessResult{}, err
	}
	return ProcessResult{Inserted: inserted}, nil
}

func insertChapterNotifications(
	ctx context.Context,
	tx pgx.Tx,
	eventID string,
	dedupeKey string,
	payload events.ChapterPublished,
) (int64, error) {
	var inserted int64
	err := tx.QueryRow(
		ctx,
		`WITH recipient_ids AS (
             SELECT sub.user_id
               FROM subscriptions sub
              WHERE sub.series_id=$1::uuid
                AND sub.user_id IS NOT NULL
                AND sub.created_at <= $2
             UNION
             SELECT b.user_id
               FROM bookmarks b
              WHERE b.series_id=$1::uuid
                AND b.user_id IS NOT NULL
                AND b.created_at <= $2
         ), recipients AS (
             SELECT ids.user_id, s.title AS series_title
               FROM recipient_ids ids
               JOIN series s ON s.id=$1::uuid
         ), inserted AS (
             INSERT INTO notifications(
                 user_id,series_id,chapter_id,message,is_read,created_at,
                 source_event_id,kind,dedupe_key
             )
             SELECT recipients.user_id,
                    $1::uuid,
                    $3::uuid,
                    LEFT('New chapter ' || $4 || ' of ' || recipients.series_title || ' is available.', 2000),
                    FALSE,
                    NOW(),
                    $5::uuid,
                    'chapter.published',
                    $6
               FROM recipients
             ON CONFLICT DO NOTHING
             RETURNING id
         )
         SELECT COUNT(*)::bigint FROM inserted`,
		payload.SeriesID,
		payload.PublishedAt,
		payload.ChapterID,
		events.ChapterLabel(payload.ChapterNumber),
		eventID,
		dedupeKey,
	).Scan(&inserted)
	if err != nil {
		return 0, fmt.Errorf("insert chapter notifications: %w", err)
	}
	return inserted, nil
}

func insertRequestedNotification(
	ctx context.Context,
	tx pgx.Tx,
	eventID string,
	payload events.NotificationRequested,
) (int64, error) {
	tag, err := tx.Exec(
		ctx,
		`INSERT INTO notifications(
             user_id,series_id,chapter_id,message,is_read,created_at,
             source_event_id,kind,dedupe_key
         ) VALUES (
             $1::uuid,$2::uuid,$3::uuid,LEFT($4,2000),FALSE,NOW(),
             $5::uuid,$6,$7
         )
         ON CONFLICT DO NOTHING`,
		payload.RecipientUserID,
		dbNullableString(payload.SeriesID),
		dbNullableString(payload.ChapterID),
		payload.Message,
		eventID,
		payload.Kind,
		payload.DedupeKey,
	)
	if err != nil {
		return 0, fmt.Errorf("insert requested notification: %w", err)
	}
	return tag.RowsAffected(), nil
}

const enqueueRealtimeBatchSQL = `SELECT enqueue_event_outbox_v1(
    'notification.batch.created',
    'notification.batch.created',
    1,
    'notification_batch',
    $1::text,
    $2::text,
    'notification-worker',
    $3::jsonb,
    NULL::uuid,
    $4::uuid,
    '{}'::jsonb,
    NOW()
)::text`

func enqueueRealtimeBatch(
	ctx context.Context,
	tx pgx.Tx,
	sourceEventID string,
	partitionKey string,
	payload map[string]any,
) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	var outboxID string
	err = tx.QueryRow(
		ctx,
		enqueueRealtimeBatchSQL,
		sourceEventID,
		partitionKey,
		string(body),
		sourceEventID,
	).Scan(&outboxID)
	if err != nil {
		return fmt.Errorf("enqueue notification realtime event: %w", err)
	}
	return nil
}

func nullableString(value *string) any {
	if value == nil || *value == "" {
		return nil
	}
	return *value
}

func dbNullableString(value *string) any {
	return nullableString(value)
}
