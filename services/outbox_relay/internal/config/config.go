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
	RabbitExchange  string
	RabbitArchive   string
	WorkerID        string
	BatchSize       int
	PollInterval    time.Duration
	ClaimStaleAfter time.Duration
	PublishTimeout  time.Duration
	RetryBase       time.Duration
	RetryMax        time.Duration
	DBMaxConns      int32
}

func Load() Config {
	dbURL := requireEnv("OUTBOX_DATABASE_URL")

	workerID := strings.TrimSpace(os.Getenv("OUTBOX_WORKER_ID"))
	if workerID == "" {
		host, _ := os.Hostname()
		if host == "" {
			host = "local"
		}
		workerID = "outbox-relay-" + host
	}

	return Config{
		Port:            getenvPort("OUTBOX_RELAY_PORT", "8080"),
		DatabaseURL:     dbURL,
		RabbitURL:       getenv("RABBITMQ_URL", "amqp://mreader:mreader@rabbitmq:5672/mreader"),
		RabbitExchange:  getenv("RABBITMQ_EVENTS_EXCHANGE", "mreader.events"),
		RabbitArchive:   getenv("RABBITMQ_EVENTS_ARCHIVE_QUEUE", "mreader.events.archive"),
		WorkerID:        workerID,
		BatchSize:       positiveInt("OUTBOX_BATCH_SIZE", 50),
		PollInterval:    durationMillis("OUTBOX_POLL_INTERVAL_MS", 500),
		ClaimStaleAfter: durationSeconds("OUTBOX_CLAIM_STALE_SECONDS", 120),
		PublishTimeout:  durationSeconds("OUTBOX_PUBLISH_TIMEOUT_SECONDS", 10),
		RetryBase:       durationSeconds("OUTBOX_RETRY_BASE_SECONDS", 1),
		RetryMax:        durationSeconds("OUTBOX_RETRY_MAX_SECONDS", 300),
		DBMaxConns:      int32(positiveInt("OUTBOX_DB_MAX_CONNS", 10)),
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

func durationSeconds(key string, fallback int) time.Duration {
	return time.Duration(positiveInt(key, fallback)) * time.Second
}

func durationMillis(key string, fallback int) time.Duration {
	return time.Duration(positiveInt(key, fallback)) * time.Millisecond
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
