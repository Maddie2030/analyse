package store

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	seriesUpdatedTopic           = "series.updated"
	seriesUpdatedEventType       = "series.updated"
	seriesUpdatedEventVersion    = 1
	seriesUpdatedProducer        = "catalog-go"
	chapterPublishedTopic        = "chapter.published"
	chapterPublishedEventType    = "chapter.published"
	chapterPublishedEventVersion = 2
	chapterPublishedProducer     = "catalog-go"
)

type EventMetadata struct {
	RequestID   string
	OperationID string
	Revision    int64
	ErrorCode   string
	Retryable   *bool
}

func eventHeaders(schema, source string, metadata EventMetadata) ([]byte, error) {
	headers := map[string]any{
		"content_type":   "application/json",
		"payload_schema": schema,
		"source":         source,
		"owner":          "catalog",
	}
	if requestID := strings.TrimSpace(metadata.RequestID); requestID != "" {
		headers["request_id"] = requestID
	}
	if operationID := strings.TrimSpace(metadata.OperationID); operationID != "" {
		headers["operation_id"] = operationID
	}
	if metadata.Revision > 0 {
		headers["revision"] = metadata.Revision
	}
	if errorCode := strings.TrimSpace(metadata.ErrorCode); errorCode != "" {
		headers["error_code"] = errorCode
	}
	if metadata.Retryable != nil {
		headers["retryable"] = *metadata.Retryable
	}
	return json.Marshal(headers)
}

func normalizeChangedFields(fields []string) []string {
	out := make([]string, 0, len(fields))
	seen := make(map[string]struct{}, len(fields))
	for _, field := range fields {
		field = strings.TrimSpace(field)
		if field == "" {
			continue
		}
		if _, ok := seen[field]; ok {
			continue
		}
		seen[field] = struct{}{}
		out = append(out, field)
	}
	return out
}

func equalIntSet(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	seen := make(map[int]int, len(a))
	for _, value := range a {
		seen[value]++
	}
	for _, value := range b {
		count := seen[value]
		if count == 0 {
			return false
		}
		if count == 1 {
			delete(seen, value)
		} else {
			seen[value] = count - 1
		}
	}
	return len(seen) == 0
}

func seriesTaxonomyIDsTx(ctx context.Context, tx pgx.Tx, table, column, seriesID string) ([]int, error) {
	if table != "series_genres" && table != "series_tags" {
		return nil, errors.New("unsupported series taxonomy table")
	}
	if column != "genre_id" && column != "tag_id" {
		return nil, errors.New("unsupported series taxonomy column")
	}
	rows, err := tx.Query(ctx, "SELECT "+column+" FROM "+table+" WHERE series_id=$1::uuid ORDER BY "+column, seriesID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	values := make([]int, 0)
	for rows.Next() {
		var value int
		if err := rows.Scan(&value); err != nil {
			return nil, err
		}
		values = append(values, value)
	}
	return values, rows.Err()
}

func enqueueSeriesUpdatedTx(
	ctx context.Context,
	tx pgx.Tx,
	seriesID string,
	seriesSlug string,
	changedFields []string,
	updatedAt time.Time,
	source string,
	metadata ...EventMetadata,
) (string, error) {
	changedFields = normalizeChangedFields(changedFields)
	if len(changedFields) == 0 {
		return "", errors.New("series.updated requires at least one changed field")
	}

	payload, err := json.Marshal(map[string]any{
		"series_id":      seriesID,
		"series_slug":    seriesSlug,
		"changed_fields": changedFields,
		"updated_at":     updatedAt.UTC().Format(time.RFC3339Nano),
	})
	if err != nil {
		return "", err
	}
	eventMetadata := EventMetadata{}
	if len(metadata) > 0 {
		eventMetadata = metadata[0]
	}
	headers, err := eventHeaders("v1/series.updated.schema.json", source, eventMetadata)
	if err != nil {
		return "", err
	}

	var eventID string
	err = tx.QueryRow(ctx, `
		SELECT enqueue_event_outbox_v1(
			$1,$2,$3,$4,$5,$6,$7,$8::jsonb,NULL,NULL,$9::jsonb,$10::timestamptz
		)::text`,
		seriesUpdatedTopic,
		seriesUpdatedEventType,
		seriesUpdatedEventVersion,
		"series",
		seriesID,
		seriesID,
		seriesUpdatedProducer,
		payload,
		headers,
		updatedAt,
	).Scan(&eventID)
	if err != nil {
		return "", err
	}
	if eventID == "" {
		return "", errors.New("failed to enqueue series.updated outbox event")
	}
	return eventID, nil
}

func enqueueChapterPublishedTx(
	ctx context.Context,
	tx pgx.Tx,
	chapterID string,
	seriesID string,
	chapterRevision int64,
	chapterNumber float64,
	chapterSlug string,
	seriesSlug string,
	title *string,
	pageCount int,
	publishedAt time.Time,
	source string,
	metadata ...EventMetadata,
) (string, error) {
	if chapterID == "" || seriesID == "" || chapterSlug == "" || seriesSlug == "" {
		return "", errors.New("chapter.published requires chapter/series identifiers and slugs")
	}
	if chapterRevision < 1 {
		return "", errors.New("chapter.published chapter_revision must be positive")
	}
	if pageCount < 0 {
		return "", errors.New("chapter.published page_count must be non-negative")
	}
	if publishedAt.IsZero() {
		publishedAt = time.Now().UTC()
	}
	payload, err := json.Marshal(map[string]any{
		"chapter_id":       chapterID,
		"series_id":        seriesID,
		"chapter_revision": chapterRevision,
		"chapter_number":   chapterNumber,
		"chapter_slug":     chapterSlug,
		"series_slug":      seriesSlug,
		"title":            title,
		"page_count":       pageCount,
		"published_at":     publishedAt.UTC().Format(time.RFC3339Nano),
	})
	if err != nil {
		return "", err
	}
	eventMetadata := EventMetadata{}
	if len(metadata) > 0 {
		eventMetadata = metadata[0]
	}
	headers, err := eventHeaders("v2/chapter.published.schema.json", source, eventMetadata)
	if err != nil {
		return "", err
	}
	var eventID string
	err = tx.QueryRow(ctx, `
		SELECT enqueue_event_outbox_v1(
			$1,$2,$3,$4,$5,$6,$7,$8::jsonb,NULL,NULL,$9::jsonb,$10::timestamptz
		)::text`,
		chapterPublishedTopic,
		chapterPublishedEventType,
		chapterPublishedEventVersion,
		"chapter",
		chapterID,
		seriesID,
		chapterPublishedProducer,
		payload,
		headers,
		publishedAt,
	).Scan(&eventID)
	if err != nil {
		return "", err
	}
	if eventID == "" {
		return "", errors.New("failed to enqueue chapter.published outbox event")
	}
	return eventID, nil
}
