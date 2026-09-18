package broker

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
	"time"

	amqp "github.com/rabbitmq/amqp091-go"
	"mreader/notification-worker/internal/config"
)

type Handler func(context.Context, []byte) error

type Consumer struct {
	cfg   config.Config
	log   *slog.Logger
	ready atomic.Bool
	mu    sync.Mutex
	conn  *amqp.Connection
}

func New(cfg config.Config, log *slog.Logger) *Consumer {
	return &Consumer{cfg: cfg, log: log}
}

func (c *Consumer) Ready() bool {
	return c.ready.Load()
}

func (c *Consumer) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.ready.Store(false)
	if c.conn == nil {
		return nil
	}
	err := c.conn.Close()
	c.conn = nil
	return err
}

func (c *Consumer) Run(ctx context.Context, handler Handler) {
	for ctx.Err() == nil {
		if err := c.consumeOnce(ctx, handler); err != nil && ctx.Err() == nil {
			c.log.Warn("notification RabbitMQ consumer disconnected", "error", err)
		}
		c.ready.Store(false)
		if !sleepContext(ctx, c.cfg.ReconnectDelay) {
			return
		}
	}
}

func (c *Consumer) consumeOnce(ctx context.Context, handler Handler) error {
	conn, err := amqp.DialConfig(c.cfg.RabbitURL, amqp.Config{
		Heartbeat: 10 * time.Second,
		Locale:    "en_US",
		Properties: amqp.Table{
			"connection_name": "mreader-notification-worker",
		},
	})
	if err != nil {
		return fmt.Errorf("rabbitmq connect: %w", err)
	}
	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	defer func() {
		c.mu.Lock()
		if c.conn == conn {
			c.conn = nil
		}
		c.mu.Unlock()
		_ = conn.Close()
	}()

	consumeCh, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("consumer channel: %w", err)
	}
	defer consumeCh.Close()

	publishCh, err := conn.Channel()
	if err != nil {
		return fmt.Errorf("publisher channel: %w", err)
	}
	defer publishCh.Close()
	if err := publishCh.Confirm(false); err != nil {
		return fmt.Errorf("publisher confirm mode: %w", err)
	}

	if err := c.declareTopology(consumeCh); err != nil {
		return err
	}
	if err := consumeCh.Qos(c.cfg.Prefetch, 0, false); err != nil {
		return fmt.Errorf("consumer qos: %w", err)
	}

	messages, err := consumeCh.Consume(
		c.cfg.Queue,
		"mreader-notification-worker",
		false,
		false,
		false,
		false,
		nil,
	)
	if err != nil {
		return fmt.Errorf("consume notification queue: %w", err)
	}

	c.ready.Store(true)
	c.log.Info("notification RabbitMQ consumer ready", "queue", c.cfg.Queue, "prefetch", c.cfg.Prefetch)

	for {
		select {
		case <-ctx.Done():
			return nil
		case delivery, ok := <-messages:
			if !ok {
				return fmt.Errorf("notification delivery channel closed")
			}
			if err := handler(ctx, delivery.Body); err == nil {
				if ackErr := delivery.Ack(false); ackErr != nil {
					return fmt.Errorf("ack notification event: %w", ackErr)
				}
				continue
			} else if routeErr := c.routeFailure(ctx, publishCh, delivery, err); routeErr != nil {
				c.log.Error("notification event failure routing failed", "error", routeErr)
				if nackErr := delivery.Nack(false, true); nackErr != nil {
					return fmt.Errorf("nack notification event after publish failure: %w", nackErr)
				}
				continue
			}
			if ackErr := delivery.Ack(false); ackErr != nil {
				return fmt.Errorf("ack routed notification event: %w", ackErr)
			}
		}
	}
}

func (c *Consumer) declareTopology(ch *amqp.Channel) error {
	if err := ch.ExchangeDeclare(c.cfg.EventsExchange, "topic", true, false, false, false, nil); err != nil {
		return fmt.Errorf("events exchange: %w", err)
	}
	if err := ch.ExchangeDeclare(c.cfg.RetryExchange, "direct", true, false, false, false, nil); err != nil {
		return fmt.Errorf("notification retry exchange: %w", err)
	}
	if err := ch.ExchangeDeclare(c.cfg.DeadExchange, "direct", true, false, false, false, nil); err != nil {
		return fmt.Errorf("notification dead exchange: %w", err)
	}

	if _, err := ch.QueueDeclare(c.cfg.Queue, true, false, false, false, amqp.Table{"x-queue-type": "quorum"}); err != nil {
		return fmt.Errorf("notification queue: %w", err)
	}
	for _, routingKey := range []string{"chapter.published", "notification.requested", "notification.worker.retry"} {
		if err := ch.QueueBind(c.cfg.Queue, routingKey, c.cfg.EventsExchange, false, nil); err != nil {
			return fmt.Errorf("notification binding %s: %w", routingKey, err)
		}
	}

	retryArgs := amqp.Table{
		"x-queue-type":              "quorum",
		"x-message-ttl":             int64(c.cfg.RetryDelay / time.Millisecond),
		"x-dead-letter-exchange":    c.cfg.EventsExchange,
		"x-dead-letter-routing-key": "notification.worker.retry",
	}
	if _, err := ch.QueueDeclare(c.cfg.RetryQueue, true, false, false, false, retryArgs); err != nil {
		return fmt.Errorf("notification retry queue: %w", err)
	}
	if err := ch.QueueBind(c.cfg.RetryQueue, c.cfg.RetryRoutingKey, c.cfg.RetryExchange, false, nil); err != nil {
		return fmt.Errorf("notification retry binding: %w", err)
	}

	if _, err := ch.QueueDeclare(c.cfg.DeadQueue, true, false, false, false, amqp.Table{"x-queue-type": "quorum"}); err != nil {
		return fmt.Errorf("notification dlq: %w", err)
	}
	if err := ch.QueueBind(c.cfg.DeadQueue, c.cfg.DeadRoutingKey, c.cfg.DeadExchange, false, nil); err != nil {
		return fmt.Errorf("notification dlq binding: %w", err)
	}
	return nil
}

func (c *Consumer) routeFailure(ctx context.Context, ch *amqp.Channel, delivery amqp.Delivery, processingErr error) error {
	attempt := headerInt(delivery.Headers, "x-mreader-attempt") + 1
	headers := cloneHeaders(delivery.Headers)
	headers["x-mreader-attempt"] = int32(attempt)
	headers["x-mreader-last-error"] = truncate(processingErr.Error(), 2000)

	exchange := c.cfg.RetryExchange
	routingKey := c.cfg.RetryRoutingKey
	destination := "retry"
	if attempt >= c.cfg.MaxAttempts {
		exchange = c.cfg.DeadExchange
		routingKey = c.cfg.DeadRoutingKey
		destination = "dlq"
	}

	publishCtx, cancel := context.WithTimeout(ctx, c.cfg.PublishTimeout)
	defer cancel()
	confirmation, err := ch.PublishWithDeferredConfirmWithContext(
		publishCtx,
		exchange,
		routingKey,
		true,
		false,
		amqp.Publishing{
			Headers:         headers,
			ContentType:     delivery.ContentType,
			ContentEncoding: delivery.ContentEncoding,
			DeliveryMode:    amqp.Persistent,
			Priority:        delivery.Priority,
			CorrelationId:   delivery.CorrelationId,
			ReplyTo:         delivery.ReplyTo,
			Expiration:      delivery.Expiration,
			MessageId:       delivery.MessageId,
			Timestamp:       delivery.Timestamp,
			Type:            delivery.Type,
			UserId:          delivery.UserId,
			AppId:           delivery.AppId,
			Body:            delivery.Body,
		},
	)
	if err != nil {
		return fmt.Errorf("publish notification %s: %w", destination, err)
	}
	if confirmation == nil {
		return fmt.Errorf("notification %s publisher confirmation unavailable", destination)
	}
	acked, err := confirmation.WaitContext(publishCtx)
	if err != nil {
		return fmt.Errorf("confirm notification %s: %w", destination, err)
	}
	if !acked {
		return fmt.Errorf("notification %s publish negatively acknowledged", destination)
	}

	c.log.Warn(
		"notification event processing failed",
		"destination", destination,
		"attempt", attempt,
		"max_attempts", c.cfg.MaxAttempts,
		"message_id", delivery.MessageId,
		"error", processingErr,
	)
	return nil
}

func headerInt(headers amqp.Table, key string) int {
	if headers == nil {
		return 0
	}
	switch value := headers[key].(type) {
	case int:
		return value
	case int8:
		return int(value)
	case int16:
		return int(value)
	case int32:
		return int(value)
	case int64:
		return int(value)
	case uint8:
		return int(value)
	case uint16:
		return int(value)
	case uint32:
		return int(value)
	case uint64:
		return int(value)
	default:
		return 0
	}
}

func cloneHeaders(source amqp.Table) amqp.Table {
	cloned := amqp.Table{}
	for key, value := range source {
		cloned[key] = value
	}
	return cloned
}

func truncate(value string, max int) string {
	if len(value) <= max {
		return value
	}
	return value[:max]
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
