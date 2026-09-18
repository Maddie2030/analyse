package events

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"
)

type Envelope struct {
	EventID       string          `json:"event_id"`
	EventType     string          `json:"event_type"`
	EventVersion  int             `json:"event_version"`
	AggregateType string          `json:"aggregate_type"`
	AggregateID   string          `json:"aggregate_id"`
	OccurredAt    time.Time       `json:"occurred_at"`
	Producer      string          `json:"producer"`
	CorrelationID string          `json:"correlation_id,omitempty"`
	CausationID   string          `json:"causation_id,omitempty"`
	Payload       json.RawMessage `json:"payload"`
}

type ChapterPublished struct {
	ChapterID       string    `json:"chapter_id"`
	SeriesID        string    `json:"series_id"`
	ChapterRevision int64     `json:"chapter_revision,omitempty"`
	ChapterNumber   float64   `json:"chapter_number"`
	ChapterSlug     string    `json:"chapter_slug"`
	SeriesSlug      string    `json:"series_slug"`
	Title           *string   `json:"title"`
	PageCount       int       `json:"page_count"`
	PublishedAt     time.Time `json:"published_at"`
}

type NotificationRequested struct {
	RecipientUserID string    `json:"recipient_user_id"`
	Kind            string    `json:"kind"`
	Message         string    `json:"message"`
	SeriesID        *string   `json:"series_id"`
	ChapterID       *string   `json:"chapter_id"`
	DedupeKey       string    `json:"dedupe_key"`
	RequestedAt     time.Time `json:"requested_at"`
}

func DecodeEnvelope(body []byte) (Envelope, error) {
	var envelope Envelope
	if err := json.Unmarshal(body, &envelope); err != nil {
		return Envelope{}, fmt.Errorf("decode event envelope: %w", err)
	}
	if strings.TrimSpace(envelope.EventID) == "" || strings.TrimSpace(envelope.EventType) == "" {
		return Envelope{}, fmt.Errorf("event envelope missing event_id or event_type")
	}
	if envelope.OccurredAt.IsZero() {
		return Envelope{}, fmt.Errorf("event envelope missing occurred_at")
	}
	if len(envelope.Payload) == 0 {
		envelope.Payload = json.RawMessage(`{}`)
	}
	return envelope, nil
}

func DecodeChapterPublished(raw json.RawMessage, eventVersion int) (ChapterPublished, error) {
	var payload ChapterPublished
	if err := json.Unmarshal(raw, &payload); err != nil {
		return ChapterPublished{}, fmt.Errorf("decode chapter.published payload: %w", err)
	}
	if payload.ChapterID == "" || payload.SeriesID == "" || payload.PublishedAt.IsZero() {
		return ChapterPublished{}, fmt.Errorf("chapter.published payload missing required identifiers/timestamp")
	}
	switch eventVersion {
	case 1:
		// Legacy publishers do not carry a Catalog publication revision.
		payload.ChapterRevision = 0
	case 2:
		if payload.ChapterRevision < 1 {
			return ChapterPublished{}, fmt.Errorf("chapter.published v2 payload missing positive chapter_revision")
		}
	default:
		return ChapterPublished{}, fmt.Errorf("unsupported chapter.published event_version %d", eventVersion)
	}
	return payload, nil
}

func ChapterPublishedDedupeKey(eventVersion int, payload ChapterPublished) (string, error) {
	base := "chapter.published:" + payload.ChapterID
	switch eventVersion {
	case 1:
		return base, nil
	case 2:
		if payload.ChapterRevision < 1 {
			return "", fmt.Errorf("chapter.published v2 requires positive chapter_revision")
		}
		return base + ":revision:" + strconv.FormatInt(payload.ChapterRevision, 10), nil
	default:
		return "", fmt.Errorf("unsupported chapter.published event_version %d", eventVersion)
	}
}

func DecodeNotificationRequested(raw json.RawMessage) (NotificationRequested, error) {
	var payload NotificationRequested
	if err := json.Unmarshal(raw, &payload); err != nil {
		return NotificationRequested{}, fmt.Errorf("decode notification.requested payload: %w", err)
	}
	if payload.RecipientUserID == "" || strings.TrimSpace(payload.Kind) == "" || strings.TrimSpace(payload.Message) == "" || strings.TrimSpace(payload.DedupeKey) == "" || payload.RequestedAt.IsZero() {
		return NotificationRequested{}, fmt.Errorf("notification.requested payload missing required fields")
	}
	return payload, nil
}

func ChapterLabel(number float64) string {
	return strconv.FormatFloat(number, 'f', -1, 64)
}
