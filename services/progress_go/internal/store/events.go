package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	progressUpdatedTopic        = "progress.updated"
	progressUpdatedEventType    = "progress.updated"
	progressUpdatedEventVersion = 2
	progressUpdatedProducer     = "progress-go"
	enqueueProgressUpdatedSQL   = `
		SELECT enqueue_event_outbox_v1(
			$1,$2,$3,$4,$5,$6,$7,$8::jsonb,NULL,NULL,$9::jsonb,$10::timestamptz
		)::text`
)

type EventMetadata struct {
	RequestID   string
	OperationID string
}

func progressAggregateID(userID, seriesID string) (string, error) {
	userID = strings.TrimSpace(userID)
	seriesID = strings.TrimSpace(seriesID)
	if userID == "" || seriesID == "" {
		return "", errors.New("progress.updated requires user_id and series_id")
	}
	return userID + ":" + seriesID, nil
}

func progressEventHeaders(source string, revision int64, sourceMessageID string, metadata EventMetadata) ([]byte, error) {
	headers := map[string]any{
		"content_type":   "application/json",
		"payload_schema": "v2/progress.updated.schema.json",
		"source":         source,
		"owner":          "progress",
		"revision":       revision,
	}
	if requestID := strings.TrimSpace(metadata.RequestID); requestID != "" {
		headers["request_id"] = requestID
	}
	if operationID := strings.TrimSpace(metadata.OperationID); operationID != "" {
		headers["operation_id"] = operationID
	}
	if sourceMessageID = strings.TrimSpace(sourceMessageID); sourceMessageID != "" {
		headers["source_message_id"] = sourceMessageID
	}
	return json.Marshal(headers)
}

func progressUpdatedEventArgs(
	userID string,
	seriesID string,
	chapterID string,
	lastPage int,
	scrollPosition float64,
	updatedAt time.Time,
	revision int64,
	sourceMessageID string,
	metadata ...EventMetadata,
) ([]any, error) {
	aggregateID, err := progressAggregateID(userID, seriesID)
	if err != nil {
		return nil, err
	}
	if lastPage < 1 {
		return nil, fmt.Errorf("progress.updated last_page must be >= 1: %d", lastPage)
	}
	if scrollPosition < 0 || scrollPosition > 1 {
		return nil, fmt.Errorf("progress.updated scroll_position must be between 0 and 1: %f", scrollPosition)
	}
	if updatedAt.IsZero() {
		return nil, errors.New("progress.updated requires updated_at")
	}
	if revision < 1 {
		return nil, errors.New("progress.updated requires a positive revision")
	}

	var chapterValue any
	if chapterID = strings.TrimSpace(chapterID); chapterID != "" {
		chapterValue = chapterID
	}
	payload, err := json.Marshal(map[string]any{
		"user_id":         userID,
		"series_id":       seriesID,
		"chapter_id":      chapterValue,
		"last_page":       lastPage,
		"scroll_position": scrollPosition,
		"updated_at":      updatedAt.UTC().Format(time.RFC3339Nano),
		"revision":        revision,
	})
	if err != nil {
		return nil, err
	}

	source := "progress-api"
	if strings.TrimSpace(sourceMessageID) != "" {
		source = "redis-stream-flusher"
	}
	eventMetadata := EventMetadata{}
	if len(metadata) > 0 {
		eventMetadata = metadata[0]
	}
	headerJSON, err := progressEventHeaders(source, revision, sourceMessageID, eventMetadata)
	if err != nil {
		return nil, err
	}

	return []any{
		progressUpdatedTopic,
		progressUpdatedEventType,
		progressUpdatedEventVersion,
		"reading_progress",
		aggregateID,
		aggregateID,
		progressUpdatedProducer,
		payload,
		headerJSON,
		updatedAt,
	}, nil
}

func enqueueProgressUpdatedTx(
	ctx context.Context,
	tx pgx.Tx,
	userID string,
	seriesID string,
	chapterID string,
	lastPage int,
	scrollPosition float64,
	updatedAt time.Time,
	revision int64,
	sourceMessageID string,
	metadata ...EventMetadata,
) (string, error) {
	args, err := progressUpdatedEventArgs(
		userID, seriesID, chapterID, lastPage, scrollPosition, updatedAt, revision, sourceMessageID, metadata...,
	)
	if err != nil {
		return "", err
	}

	var eventID string
	if err := tx.QueryRow(ctx, enqueueProgressUpdatedSQL, args...).Scan(&eventID); err != nil {
		return "", err
	}
	if eventID == "" {
		return "", errors.New("failed to enqueue progress.updated outbox event")
	}
	return eventID, nil
}
