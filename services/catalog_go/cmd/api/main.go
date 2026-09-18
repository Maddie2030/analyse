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
	"mreader/catalog/internal/cache"
	"mreader/catalog/internal/config"
	"mreader/catalog/internal/httpapi"
	"mreader/catalog/internal/session"
	"mreader/catalog/internal/store"
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
		Addr: cfg.RedisAddr, DB: cfg.RedisDB, PoolSize: cfg.RedisPoolSize,
		MinIdleConns: 1, PoolTimeout: 3 * time.Second,
	})
	defer rdb.Close()
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Error("ping critical valkey", "error", err)
		os.Exit(1)
	}
	cacheRDB := rdb
	if cfg.CacheRedisAddr != cfg.RedisAddr {
		cacheRDB = redis.NewClient(&redis.Options{
			Addr: cfg.CacheRedisAddr, DB: cfg.RedisDB, PoolSize: cfg.RedisPoolSize,
			MinIdleConns: 1, PoolTimeout: 3 * time.Second,
		})
		defer cacheRDB.Close()
		if err := cacheRDB.Ping(ctx).Err(); err != nil {
			log.Error("ping cache valkey", "error", err)
			os.Exit(1)
		}
	}
	cacheSvc := cache.New(cacheRDB)
	cacheCtx, cacheCancel := context.WithCancel(context.Background())
	defer cacheCancel()
	go cacheSvc.RunInvalidationLoop(cacheCtx)
	api := httpapi.New(store.New(db), session.New(rdb, cfg.SessionCookie), cacheSvc, cfg.EnableWrites, cfg.InternalToken, log)
	srv := &http.Server{Addr: ":" + cfg.Port, Handler: api.Router(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		log.Info("catalog-go shadow service started", "port", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	shutdownCtx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.ShutdownSeconds)*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
}
