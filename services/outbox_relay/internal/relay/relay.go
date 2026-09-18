package relay

import (
	"context"
	"log/slog"
	"math"
	"time"

	"mreader/outbox-relay/internal/broker"
	"mreader/outbox-relay/internal/outbox"
)

type Relay struct {
	store           *outbox.Store
	publisher       *broker.Publisher
	log             *slog.Logger
	workerID        string
	batchSize       int
	pollInterval    time.Duration
	claimStaleAfter time.Duration
	publishTimeout  time.Duration
	retryBase       time.Duration
	retryMax        time.Duration
}

func New(
	store *outbox.Store,
	publisher *broker.Publisher,
	log *slog.Logger,
	workerID string,
	batchSize int,
	pollInterval time.Duration,
	claimStaleAfter time.Duration,
	publishTimeout time.Duration,
	retryBase time.Duration,
	retryMax time.Duration,
) *Relay {
	return &Relay{
		store:           store,
		publisher:       publisher,
		log:             log,
		workerID:        workerID,
		batchSize:       batchSize,
		pollInterval:    pollInterval,
		claimStaleAfter: claimStaleAfter,
		publishTimeout:  publishTimeout,
		retryBase:       retryBase,
		retryMax:        retryMax,
	}
}

func (r *Relay) Run(ctx context.Context) {
	defer r.releaseLocks()

	for {
		if ctx.Err() != nil {
			return
		}

		events, err := r.store.Claim(
			ctx,
			r.workerID,
			r.batchSize,
			r.claimStaleAfter,
		)
		if err != nil {
			r.log.Error("outbox claim failed", "error", err)
			if !sleepContext(ctx, r.pollInterval) {
				return
			}
			continue
		}

		if len(events) == 0 {
			if !sleepContext(ctx, r.pollInterval) {
				return
			}
			continue
		}

		for _, event := range events {
			if ctx.Err() != nil {
				return
			}
			r.publishOne(ctx, event)
		}
	}
}

func (r *Relay) publishOne(ctx context.Context, event outbox.Event) {
	publishCtx, cancel := context.WithTimeout(ctx, r.publishTimeout)
	err := r.publisher.Publish(publishCtx, event)
	cancel()

	if err != nil {
		nextAttempt := time.Now().UTC().Add(r.retryDelay(event.AttemptCount))
		markCtx, markCancel := context.WithTimeout(context.Background(), 5*time.Second)
		markErr := r.store.MarkFailed(
			markCtx,
			event.EventID,
			r.workerID,
			nextAttempt,
			truncateError(err.Error(), 4000),
		)
		markCancel()
		if markErr != nil {
			r.log.Error(
				"outbox publish failed and retry state update failed",
				"event_id", event.EventID,
				"topic", event.Topic,
				"correlation_id", event.CorrelationID,
				"aggregate_id", event.AggregateID,
				"attempt", event.AttemptCount,
				"publish_error", err,
				"state_error", markErr,
			)
			return
		}
		r.log.Warn(
			"outbox publish failed; retry scheduled",
			"event_id", event.EventID,
			"topic", event.Topic,
			"correlation_id", event.CorrelationID,
			"aggregate_id", event.AggregateID,
			"attempt", event.AttemptCount,
			"next_attempt_at", nextAttempt,
			"error", err,
		)
		return
	}

	markCtx, markCancel := context.WithTimeout(context.Background(), 5*time.Second)
	err = r.store.MarkPublished(markCtx, event.EventID, r.workerID)
	markCancel()
	if err != nil {
		// RabbitMQ has already confirmed the record. Leaving the row unpublished
		// intentionally gives at-least-once delivery; a later relay may publish
		// the same event_id again, so every consumer must be idempotent.
		r.log.Error(
			"RabbitMQ confirmed event but outbox acknowledgement failed",
			"event_id", event.EventID,
			"topic", event.Topic,
			"correlation_id", event.CorrelationID,
			"aggregate_id", event.AggregateID,
			"attempt", event.AttemptCount,
			"error", err,
		)
		return
	}

	r.log.Info(
		"outbox event published",
		"event_id", event.EventID,
		"event_type", event.EventType,
		"topic", event.Topic,
		"correlation_id", event.CorrelationID,
		"aggregate_id", event.AggregateID,
		"attempt", event.AttemptCount,
	)
}

func (r *Relay) retryDelay(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	exponent := math.Min(float64(attempt-1), 16)
	delay := time.Duration(float64(r.retryBase) * math.Pow(2, exponent))
	if delay > r.retryMax {
		return r.retryMax
	}
	return delay
}

func (r *Relay) releaseLocks() {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := r.store.ReleaseWorkerLocks(ctx, r.workerID); err != nil {
		r.log.Error("outbox worker lock release failed", "error", err)
	}
}

func sleepContext(ctx context.Context, duration time.Duration) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

func truncateError(value string, max int) string {
	if len(value) <= max {
		return value
	}
	return value[:max]
}
