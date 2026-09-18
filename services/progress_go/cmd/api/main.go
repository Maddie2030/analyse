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
	"mreader/progress/internal/config"
	"mreader/progress/internal/httpapi"
	"mreader/progress/internal/progress"
	"mreader/progress/internal/session"
	"mreader/progress/internal/store"
)

func main() {
	cfg := config.Load()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	ctx, cancel := signal.NotifyContext(
		context.Background(),
		syscall.SIGINT,
		syscall.SIGTERM,
	)
	defer cancel()

	poolCfg, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		log.Error("invalid database url", "error", err)
		os.Exit(1)
	}
	poolCfg.MaxConns = cfg.DBMaxConns

	db, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		log.Error("database connect failed", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	if err := db.Ping(ctx); err != nil {
		log.Error("database ping failed", "error", err)
		os.Exit(1)
	}

	rdb := redis.NewClient(&redis.Options{
		Addr: cfg.RedisAddr, DB: cfg.RedisDB, PoolSize: cfg.RedisPoolSize,
		MinIdleConns: 1, PoolTimeout: 3 * time.Second,
	})
	defer rdb.Close()

	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Error("critical valkey ping failed", "error", err)
		os.Exit(1)
	}

	cacheRDB := rdb
	if cfg.DrainLegacyStream && (cfg.CacheRedisAddr != cfg.RedisAddr || cfg.CacheRedisDB != cfg.RedisDB) {
		cacheRDB = redis.NewClient(&redis.Options{
			Addr: cfg.CacheRedisAddr, DB: cfg.CacheRedisDB, PoolSize: cfg.CacheRedisPoolSize,
			MinIdleConns: 1, PoolTimeout: 3 * time.Second,
		})
		defer cacheRDB.Close()
		if err := cacheRDB.Ping(ctx).Err(); err != nil {
			log.Error("cache valkey ping failed", "error", err)
			os.Exit(1)
		}
	}

	st := store.New(db)
	if err := st.ValidateReadingSchema(ctx); err != nil {
		log.Error("reading schema migration required", "error", err)
		os.Exit(1)
	}
	progressService := progress.New(
		rdb,
		cacheRDB,
		st,
		log,
		cfg.StreamName,
		cfg.ConsumerGroup,
		cfg.ConsumerName,
		cfg.FlushBatch,
		cfg.ReclaimMinIdle,
		cfg.ReclaimInterval,
	)

	// Only a deliberate maintenance drain may process old stream messages.
	// Normal runtime has one synchronous PostgreSQL command writer.
	if cfg.DrainLegacyStream {
		log.Warn("maintenance-only legacy progress drain; HTTP command API is disabled")
		progressService.RunFlusher(ctx)
		return
	}

	api := httpapi.New(
		st,
		progressService,
		session.New(rdb, cfg.SessionCookie),
		log,
	)

	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           api.Router(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		log.Info("progress service started", "port", cfg.Port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("http server failed", "error", err)
			cancel()
		}
	}()

	<-ctx.Done()

	shutdownCtx, shutdownCancel := context.WithTimeout(
		context.Background(),
		10*time.Second,
	)
	defer shutdownCancel()

	_ = server.Shutdown(shutdownCtx)
}
