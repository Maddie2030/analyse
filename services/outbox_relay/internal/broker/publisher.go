package broker

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
	"mreader/outbox-relay/internal/outbox"
)

type Publisher struct {
	url          string
	exchange     string
	archiveQueue string
	mu           sync.Mutex
	conn         *amqp.Connection
	channel      *amqp.Channel
}

type envelope struct {
	EventID       string          `json:"event_id"`
	EventType     string          `json:"event_type"`
	EventVersion  int             `json:"event_version"`
	AggregateType string          `json:"aggregate_type"`
	AggregateID   string          `json:"aggregate_id"`
	OccurredAt    string          `json:"occurred_at"`
	Producer      string          `json:"producer"`
	CorrelationID string          `json:"correlation_id,omitempty"`
	CausationID   string          `json:"causation_id,omitempty"`
	Metadata      map[string]any  `json:"metadata,omitempty"`
	Payload       json.RawMessage `json:"payload"`
}

func New(url, exchange, archiveQueue string) *Publisher {
	return &Publisher{url: url, exchange: exchange, archiveQueue: archiveQueue}
}

func (p *Publisher) Close() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	var first error
	if p.channel != nil {
		if err := p.channel.Close(); err != nil && first == nil {
			first = err
		}
	}
	if p.conn != nil {
		if err := p.conn.Close(); err != nil && first == nil {
			first = err
		}
	}
	p.channel = nil
	p.conn = nil
	return first
}

func (p *Publisher) invalidateLocked() {
	if p.channel != nil {
		_ = p.channel.Close()
	}
	if p.conn != nil {
		_ = p.conn.Close()
	}
	p.channel = nil
	p.conn = nil
}

func (p *Publisher) ensureLocked() error {
	if p.conn != nil && !p.conn.IsClosed() && p.channel != nil && !p.channel.IsClosed() {
		return nil
	}
	p.invalidateLocked()

	conn, err := amqp.DialConfig(p.url, amqp.Config{
		Heartbeat: 10 * time.Second,
		Locale:    "en_US",
		Properties: amqp.Table{
			"connection_name": "mreader-outbox-relay",
		},
	})
	if err != nil {
		return fmt.Errorf("rabbitmq connect: %w", err)
	}
	ch, err := conn.Channel()
	if err != nil {
		_ = conn.Close()
		return fmt.Errorf("rabbitmq channel: %w", err)
	}
	if err := ch.Confirm(false); err != nil {
		_ = ch.Close()
		_ = conn.Close()
		return fmt.Errorf("rabbitmq confirm mode: %w", err)
	}
	if err := ch.ExchangeDeclare(p.exchange, "topic", true, false, false, false, nil); err != nil {
		_ = ch.Close()
		_ = conn.Close()
		return fmt.Errorf("rabbitmq event exchange: %w", err)
	}
	// A bounded catch-all archive prevents currently-unbound domain events from
	// disappearing while MReader still has few event consumers. PostgreSQL's
	// event_outbox remains the authoritative event history.
	if p.archiveQueue != "" {
		_, err = ch.QueueDeclare(
			p.archiveQueue,
			true,
			false,
			false,
			false,
			amqp.Table{
				"x-queue-type":  "quorum",
				"x-message-ttl": int64(7 * 24 * time.Hour / time.Millisecond),
				"x-max-length":  int64(100000),
			},
		)
		if err != nil {
			_ = ch.Close()
			_ = conn.Close()
			return fmt.Errorf("rabbitmq archive queue: %w", err)
		}
		if err := ch.QueueBind(p.archiveQueue, "#", p.exchange, false, nil); err != nil {
			_ = ch.Close()
			_ = conn.Close()
			return fmt.Errorf("rabbitmq archive binding: %w", err)
		}
	}
	p.conn = conn
	p.channel = ch
	return nil
}

func (p *Publisher) Ping(_ context.Context) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.ensureLocked()
}

func (p *Publisher) Publish(ctx context.Context, event outbox.Event) error {
	metadata, err := safeMetadata(event.Headers)
	if err != nil {
		return err
	}
	body, err := json.Marshal(envelope{
		EventID:       event.EventID,
		EventType:     event.EventType,
		EventVersion:  event.EventVersion,
		AggregateType: event.AggregateType,
		AggregateID:   event.AggregateID,
		OccurredAt:    event.OccurredAt.UTC().Format(time.RFC3339Nano),
		Producer:      event.Producer,
		CorrelationID: event.CorrelationID,
		CausationID:   event.CausationID,
		Metadata:      metadata,
		Payload:       event.Payload,
	})
	if err != nil {
		return err
	}
	headers, err := rabbitHeaders(event.Headers)
	if err != nil {
		return err
	}
	headers["event_id"] = event.EventID
	headers["event_type"] = event.EventType
	headers["event_version"] = int32(event.EventVersion)
	headers["aggregate_id"] = event.AggregateID
	headers["partition_key"] = event.PartitionKey

	p.mu.Lock()
	defer p.mu.Unlock()
	if err := p.ensureLocked(); err != nil {
		return err
	}

	confirmation, err := p.channel.PublishWithDeferredConfirmWithContext(
		ctx,
		p.exchange,
		event.Topic,
		true,
		false,
		amqp.Publishing{
			Headers:       headers,
			ContentType:   "application/json",
			DeliveryMode:  amqp.Persistent,
			MessageId:     event.EventID,
			CorrelationId: event.CorrelationID,
			Timestamp:     event.OccurredAt,
			Body:          body,
			Type:          event.EventType,
			AppId:         event.Producer,
		},
	)
	if err != nil {
		p.invalidateLocked()
		return fmt.Errorf("rabbitmq publish: %w", err)
	}
	if confirmation == nil {
		p.invalidateLocked()
		return fmt.Errorf("rabbitmq publisher confirmation unavailable")
	}
	acked, err := confirmation.WaitContext(ctx)
	if err != nil {
		p.invalidateLocked()
		return fmt.Errorf("rabbitmq publish confirm: %w", err)
	}
	if !acked {
		return fmt.Errorf("rabbitmq negatively acknowledged event %s", event.EventID)
	}
	return nil
}

func rabbitHeaders(raw json.RawMessage) (amqp.Table, error) {
	headers := amqp.Table{}
	if len(raw) == 0 || string(raw) == "null" || string(raw) == "{}" {
		return headers, nil
	}
	var values map[string]json.RawMessage
	if err := json.Unmarshal(raw, &values); err != nil {
		return nil, fmt.Errorf("decode outbox headers: %w", err)
	}
	for key, value := range values {
		var text string
		if err := json.Unmarshal(value, &text); err == nil {
			headers[key] = text
			continue
		}
		headers[key] = string(value)
	}
	return headers, nil
}

func safeMetadata(raw json.RawMessage) (map[string]any, error) {
	if len(raw) == 0 || string(raw) == "null" || string(raw) == "{}" {
		return nil, nil
	}
	var values map[string]json.RawMessage
	if err := json.Unmarshal(raw, &values); err != nil {
		return nil, fmt.Errorf("decode outbox metadata: %w", err)
	}
	allowed := map[string]struct{}{
		"owner":        {},
		"request_id":   {},
		"operation_id": {},
		"revision":     {},
		"error_code":   {},
		"retryable":    {},
	}
	metadata := make(map[string]any, len(allowed))
	for key := range allowed {
		rawValue, ok := values[key]
		if !ok {
			continue
		}
		var value any
		if err := json.Unmarshal(rawValue, &value); err != nil {
			return nil, fmt.Errorf("decode outbox metadata %s: %w", key, err)
		}
		switch value.(type) {
		case nil, string, float64, bool:
			metadata[key] = value
		}
	}
	if len(metadata) == 0 {
		return nil, nil
	}
	return metadata, nil
}
