package config

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port                           string
	DatabaseURL                    string
	RedisAddr                      string
	RedisDB                        int
	RedisPoolSize                  int
	CacheRedisAddr                 string
	CacheRedisDB                   int
	CacheRedisPoolSize             int
	SessionCookie                  string
	DBMaxConns                     int32
	ShutdownSeconds                int
	TokenSecret                    string
	ImageTokenTTL                  int
	SeaweedFilerURL                string
	AllowedOrigins                 []string
	Debug                          bool
	AllowSessionlessImageDelivery  bool
	TrendingEnabled                bool
	TrendingDedupeTTLSeconds       int
	TrendingQueueSize              int
	TrendingWorkers                int
	TrendingRetentionDays          int
	CloudFrontSignedCookiesEnabled bool
	CloudFrontPrivateKeyPEM        string
	CloudFrontPublicKeyID          string
	CloudFrontResourceBaseURL      string
	CloudFrontCookieDomain         string
	CloudFrontCookieTTLSeconds     int
}

func Load() Config {
	dbURL := requireEnv("READER_GO_DATABASE_URL")

	redisAddr := getenv("READER_GO_REDIS_ADDR", "redis:6379")
	return Config{
		Port:               getenvPort("READER_GO_PORT", "8080"),
		DatabaseURL:        dbURL,
		RedisAddr:          redisAddr,
		RedisDB:            getenvInt("READER_GO_REDIS_DB", 0),
		RedisPoolSize:      getenvInt("READER_GO_REDIS_POOL_SIZE", 12),
		CacheRedisAddr:     getenv("READER_GO_CACHE_REDIS_ADDR", redisAddr),
		CacheRedisDB:       getenvInt("READER_GO_CACHE_REDIS_DB", getenvInt("READER_GO_REDIS_DB", 0)),
		CacheRedisPoolSize: getenvInt("READER_GO_CACHE_REDIS_POOL_SIZE", 8),
		SessionCookie:      getenv("SESSION_COOKIE_NAME", "session_id"),
		DBMaxConns:         int32(getenvInt("READER_GO_DB_MAX_CONNS", 14)),
		ShutdownSeconds:    getenvInt("READER_GO_SHUTDOWN_SECONDS", 10),
		TokenSecret:        getenv("TOKEN_SECRET", "change-me-in-production"),
		ImageTokenTTL:      getenvInt("IMAGE_TOKEN_TTL_SECONDS", 300),
		SeaweedFilerURL: strings.TrimRight(
			getenv("SEAWEEDFS_FILER_URL", "http://seaweedfs-filer:8888"),
			"/",
		),
		AllowedOrigins: splitCSV(getenv(
			"ALLOWED_ORIGIN",
			"http://localhost:5173,http://localhost:3000",
		)),
		Debug:                          getenvBool("DEBUG", false),
		AllowSessionlessImageDelivery:  getenvBool("IMAGE_GRANT_ALLOW_SESSIONLESS_DELIVERY", false),
		TrendingEnabled:                getenvBool("READER_TRENDING_ENABLED", true),
		TrendingDedupeTTLSeconds:       getenvInt("READER_TRENDING_DEDUPE_TTL_SECONDS", 1800),
		TrendingQueueSize:              getenvInt("READER_TRENDING_QUEUE_SIZE", 4096),
		TrendingWorkers:                getenvInt("READER_TRENDING_WORKERS", 2),
		TrendingRetentionDays:          getenvInt("READER_TRENDING_RETENTION_DAYS", 45),
		CloudFrontSignedCookiesEnabled: getenvBool("CLOUDFRONT_SIGNED_COOKIES_ENABLED", false),
		CloudFrontPrivateKeyPEM:        getenv("CLOUDFRONT_SIGNING_PRIVATE_KEY_PEM", ""),
		CloudFrontPublicKeyID:          getenv("CLOUDFRONT_PUBLIC_KEY_ID", ""),
		CloudFrontResourceBaseURL:      strings.TrimRight(getenv("CLOUDFRONT_RESOURCE_BASE_URL", ""), "/"),
		CloudFrontCookieDomain:         getenv("CLOUDFRONT_COOKIE_DOMAIN", ""),
		CloudFrontCookieTTLSeconds:     getenvInt("CLOUDFRONT_COOKIE_TTL_SECONDS", getenvInt("IMAGE_TOKEN_TTL_SECONDS", 300)),
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
	raw := strings.TrimSpace(strings.ToLower(os.Getenv(key)))
	if raw == "" {
		return def
	}
	switch raw {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return def
	}
}

func splitCSV(raw string) []string {
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
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
