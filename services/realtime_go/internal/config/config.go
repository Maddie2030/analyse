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
	RedisURL        string
	RedisPoolSize   int
	RabbitURL       string
	EventsExchange  string
	SessionCookie   string
	DBMaxConns      int32
	ReconnectDelay  time.Duration
	WriteTimeout    time.Duration
	PongWait        time.Duration
	PingPeriod      time.Duration
	SessionRecheck  time.Duration
	MaxMessageBytes int64
}

func Load() Config {
	dbURL := requireEnv("REALTIME_DATABASE_URL")

	pongWait := durationSeconds("REALTIME_PONG_WAIT_SECONDS", 60)
	pingPeriod := durationSeconds("REALTIME_PING_PERIOD_SECONDS", 25)
	if pingPeriod >= pongWait {
		pingPeriod = pongWait / 2
	}

	return Config{
		Port:            getenvPort("REALTIME_PORT", "8080"),
		DatabaseURL:     dbURL,
		RedisURL:        getenv("REDIS_URL", "redis://redis:6379/0"),
		RedisPoolSize:   positiveInt("REALTIME_REDIS_POOL_SIZE", 8),
		RabbitURL:       getenv("RABBITMQ_URL", "amqp://mreader:mreader@rabbitmq:5672/mreader"),
		EventsExchange:  getenv("RABBITMQ_EVENTS_EXCHANGE", "mreader.events"),
		SessionCookie:   getenv("SESSION_COOKIE_NAME", "session_id"),
		DBMaxConns:      int32(positiveInt("REALTIME_DB_MAX_CONNS", 6)),
		ReconnectDelay:  durationMillis("REALTIME_RECONNECT_DELAY_MS", 2000),
		WriteTimeout:    durationSeconds("REALTIME_WRITE_TIMEOUT_SECONDS", 10),
		PongWait:        pongWait,
		PingPeriod:      pingPeriod,
		SessionRecheck:  durationSeconds("REALTIME_SESSION_RECHECK_SECONDS", 60),
		MaxMessageBytes: int64(positiveInt("REALTIME_MAX_MESSAGE_BYTES", 16384)),
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
