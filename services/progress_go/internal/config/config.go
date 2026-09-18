package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port               string
	DatabaseURL        string
	RedisAddr          string
	RedisDB            int
	RedisPoolSize      int
	CacheRedisAddr     string
	CacheRedisDB       int
	CacheRedisPoolSize int
	SessionCookie      string
	DBMaxConns         int32
	StreamName         string
	ConsumerGroup      string
	ConsumerName       string
	FlushBatch         int64
	ReclaimMinIdle     int
	ReclaimInterval    int
	DrainLegacyStream  bool
}

func Load() Config {
	dbURL := requireEnv("PROGRESS_GO_DATABASE_URL")

	return Config{
		Port:               getenvPort("PROGRESS_GO_PORT", "8080"),
		DatabaseURL:        dbURL,
		RedisAddr:          getenv("PROGRESS_GO_REDIS_ADDR", "redis:6379"),
		RedisDB:            getenvInt("PROGRESS_GO_REDIS_DB", 0),
		RedisPoolSize:      getenvInt("PROGRESS_GO_REDIS_POOL_SIZE", 8),
		CacheRedisAddr:     getenv("PROGRESS_GO_CACHE_REDIS_ADDR", getenv("PROGRESS_GO_REDIS_ADDR", "redis:6379")),
		CacheRedisDB:       getenvInt("PROGRESS_GO_CACHE_REDIS_DB", getenvInt("PROGRESS_GO_REDIS_DB", 0)),
		CacheRedisPoolSize: getenvInt("PROGRESS_GO_CACHE_REDIS_POOL_SIZE", 6),
		SessionCookie:      getenv("SESSION_COOKIE_NAME", "session_id"),
		DBMaxConns:         int32(getenvInt("PROGRESS_GO_DB_MAX_CONNS", 6)),
		StreamName:         getenv("PROGRESS_GO_STREAM", "progress:updates"),
		ConsumerGroup:      getenv("PROGRESS_GO_CONSUMER_GROUP", "progress-db-writers"),
		ConsumerName:       getenv("PROGRESS_GO_CONSUMER_NAME", "progress-go-1"),
		FlushBatch:         int64(getenvInt("PROGRESS_GO_FLUSH_BATCH", 100)),
		ReclaimMinIdle:     getenvInt("PROGRESS_GO_RECLAIM_MIN_IDLE_SECONDS", 30),
		ReclaimInterval:    getenvInt("PROGRESS_GO_RECLAIM_INTERVAL_SECONDS", 10),
		DrainLegacyStream:  getenv("PROGRESS_GO_DRAIN_LEGACY_STREAM", "0") == "1",
	}
}

func requireEnv(key string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		panic(key + " is required")
	}
	return value
}

func getenv(key, def string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return def
}

func getenvInt(key string, def int) int {
	raw := os.Getenv(key)
	if raw == "" {
		return def
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return def
	}
	return value
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
