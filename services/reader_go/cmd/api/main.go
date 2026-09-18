package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"mreader/reader/internal/analytics"
	"mreader/reader/internal/cloudfrontcookie"
	"mreader/reader/internal/config"
	"mreader/reader/internal/httpapi"
	"mreader/reader/internal/imagetoken"
	"mreader/reader/internal/session"
	"mreader/reader/internal/store"
)

func main() {
	cfg := config.Load()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	ctx := context.Background()

	pcfg, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		log.Error("parse db config", "error", err)
		os.Exit(1)
	}
	pcfg.MaxConns = cfg.DBMaxConns

	db, err := pgxpool.NewWithConfig(ctx, pcfg)
	if err != nil {
		log.Error("connect db", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	if err := db.Ping(ctx); err != nil {
		log.Error("ping db", "error", err)
		os.Exit(1)
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:         cfg.RedisAddr,
		DB:           cfg.RedisDB,
		PoolSize:     cfg.RedisPoolSize,
		MinIdleConns: 1,
		PoolTimeout:  3 * time.Second,
	})
	defer rdb.Close()

	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Error("ping critical valkey", "error", err)
		os.Exit(1)
	}

	cacheRDB := rdb
	if cfg.CacheRedisAddr != cfg.RedisAddr || cfg.CacheRedisDB != cfg.RedisDB {
		cacheRDB = redis.NewClient(&redis.Options{
			Addr: cfg.CacheRedisAddr, DB: cfg.CacheRedisDB, PoolSize: cfg.CacheRedisPoolSize,
			MinIdleConns: 1, PoolTimeout: 3 * time.Second,
		})
		defer cacheRDB.Close()
		if err := cacheRDB.Ping(ctx).Err(); err != nil {
			log.Error("ping cache valkey", "error", err)
			os.Exit(1)
		}
	}

	var cloudFrontSigner *cloudfrontcookie.Signer
	if cfg.CloudFrontSignedCookiesEnabled {
		cloudFrontSigner, err = cloudfrontcookie.New(
			cfg.CloudFrontPrivateKeyPEM,
			cfg.CloudFrontPublicKeyID,
			cfg.CloudFrontResourceBaseURL,
			cfg.CloudFrontCookieDomain,
			time.Duration(cfg.CloudFrontCookieTTLSeconds)*time.Second,
		)
		if err != nil {
			log.Error("configure CloudFront signed cookies", "error", err)
			os.Exit(1)
		}
	}

	var trending *analytics.Tracker
	if cfg.TrendingEnabled {
		trending = analytics.New(
			db, cacheRDB, log,
			time.Duration(cfg.TrendingDedupeTTLSeconds)*time.Second,
			cfg.TrendingQueueSize, cfg.TrendingWorkers, cfg.TrendingRetentionDays,
		)
	}

	api := httpapi.New(
		store.New(db),
		session.New(rdb, cfg.SessionCookie),
		imagetoken.New(cacheRDB, cfg.TokenSecret, cfg.ImageTokenTTL),
		trending,
		log,
		cfg.SeaweedFilerURL,
		cfg.AllowedOrigins,
		cfg.Debug,
		cfg.AllowSessionlessImageDelivery,
		cloudFrontSigner,
	)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.Router(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		log.Info(
			"reader-go shadow service started",
			"port", cfg.Port,
			"request_logging", true,
		)

		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig

	shutdownCtx, cancel := context.WithTimeout(
		context.Background(),
		time.Duration(cfg.ShutdownSeconds)*time.Second,
	)
	defer cancel()

	_ = srv.Shutdown(shutdownCtx)
	if trending != nil {
		if err := trending.Close(shutdownCtx); err != nil {
			log.Warn("trending analytics shutdown incomplete", "error", err)
		}
	}
}
