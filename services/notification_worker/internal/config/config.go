package config

import (
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Port            string
	DatabaseURL     string
	RabbitURL       string
	EventsExchange  string
	Queue           string
	RetryExchange   string
	RetryQueue      string
	RetryRoutingKey string
	DeadExchange    string
	DeadQueue       string
	DeadRoutingKey  string
	RetryDelay      time.Duration
	MaxAttempts     int
	Prefetch        int
	DBMaxConns      int32
	ReconnectDelay  time.Duration
	PublishTimeout  time.Duration
}

func Load() Config {
	dbURL := requireEnv("NOTIFICATION_DATABASE_URL")

	return Config{
		Port:            getenvPort("NOTIFICATION_WORKER_PORT", "8080"),
		DatabaseURL:     dbURL,
		RabbitURL:       getenv("RABBITMQ_URL", "amqp://mreader:mreader@rabbitmq:5672/mreader"),
		EventsExchange:  getenv("RABBITMQ_EVENTS_EXCHANGE", "mreader.events"),
		Queue:           getenv("NOTIFICATION_WORKER_QUEUE", "mreader.notification.worker"),
		RetryExchange:   getenv("NOTIFICATION_RETRY_EXCHANGE", "mreader.notification.retry"),
		RetryQueue:      getenv("NOTIFICATION_RETRY_QUEUE", "mreader.notification.worker.retry"),
		RetryRoutingKey: getenv("NOTIFICATION_RETRY_ROUTING_KEY", "notification.worker"),
		DeadExchange:    getenv("NOTIFICATION_DEAD_EXCHANGE", "mreader.notification.dead"),
		DeadQueue:       getenv("NOTIFICATION_DEAD_QUEUE", "mreader.notification.worker.dlq"),
		DeadRoutingKey:  getenv("NOTIFICATION_DEAD_ROUTING_KEY", "notification.worker"),
		RetryDelay:      durationMillis("NOTIFICATION_RETRY_DELAY_MS", positiveInt("RABBITMQ_RETRY_DELAY_MS", 5000)),
		MaxAttempts:     positiveInt("NOTIFICATION_MAX_ATTEMPTS", positiveInt("RABBITMQ_MAX_ATTEMPTS", 3)),
		Prefetch:        positiveInt("NOTIFICATION_PREFETCH", 8),
		DBMaxConns:      int32(positiveInt("NOTIFICATION_DB_MAX_CONNS", 8)),
		ReconnectDelay:  durationMillis("NOTIFICATION_RECONNECT_DELAY_MS", 2000),
		PublishTimeout:  durationSeconds("NOTIFICATION_PUBLISH_TIMEOUT_SECONDS", 10),
	}
}

func requireEnv(key string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		panic(key + " is required")
	}
	return value
}

func getenv(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func positiveInt(key string, fallback int) int {
	value, err := strconv.Atoi(strings.TrimSpace(os.Getenv(key)))
	if err != nil || value <= 0 {
		return fallback
	}
	return value
}

func durationMillis(key string, fallback int) time.Duration {
	return time.Duration(positiveInt(key, fallback)) * time.Millisecond
}

func durationSeconds(key string, fallback int) time.Duration {
	return time.Duration(positiveInt(key, fallback)) * time.Second
}

func getenvPort(key, fallback string) string {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	port, err := strconv.Atoi(raw)
	if err != nil || port < 1 || port > 65535 {
		return fallback
	}
	return strconv.Itoa(port)
}
