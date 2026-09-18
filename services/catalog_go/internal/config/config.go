package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port            string
	DatabaseURL     string
	RedisAddr       string
	CacheRedisAddr  string
	RedisDB         int
	RedisPoolSize   int
	SessionCookie   string
	DBMaxConns      int32
	ShutdownSeconds int
	EnableWrites    bool
	InternalToken   string
}

func Load() Config {
	port := getenvPort("CATALOG_GO_PORT", "8080")
	dbURL := requireEnv("CATALOG_GO_DATABASE_URL")
	redisAddr := getenv("CATALOG_GO_REDIS_ADDR", "redis:6379")
	return Config{
		Port:            port,
		DatabaseURL:     dbURL,
		RedisAddr:       redisAddr,
		CacheRedisAddr:  getenv("CATALOG_GO_CACHE_REDIS_ADDR", redisAddr),
		RedisDB:         getenvInt("CATALOG_GO_REDIS_DB", 0),
		RedisPoolSize:   getenvInt("CATALOG_GO_REDIS_POOL_SIZE", 8),
		SessionCookie:   getenv("SESSION_COOKIE_NAME", "session_id"),
		DBMaxConns:      int32(getenvInt("CATALOG_GO_DB_MAX_CONNS", 10)),
		ShutdownSeconds: getenvInt("CATALOG_GO_SHUTDOWN_SECONDS", 10),
		EnableWrites:    getenvBool("CATALOG_GO_ENABLE_WRITES", false),
		InternalToken:   strings.TrimSpace(os.Getenv("CATALOG_INTERNAL_TOKEN")),
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
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	raw := os.Getenv(key)
	if raw == "" {
		return def
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return def
	}
	return n
}

func getenvBool(key string, def bool) bool {
	raw := os.Getenv(key)
	if raw == "" {
		return def
	}
	v, err := strconv.ParseBool(raw)
	if err != nil {
		return def
	}
	return v
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
