package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"mreader/outbox-relay/internal/broker"
	"mreader/outbox-relay/internal/config"
	"mreader/outbox-relay/internal/outbox"
	relayworker "mreader/outbox-relay/internal/relay"
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
		log.Error("database pool creation failed", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	if err := db.Ping(ctx); err != nil {
		log.Error("database ping failed", "error", err)
		os.Exit(1)
	}

	store := outbox.New(db)
	publisher := broker.New(cfg.RabbitURL, cfg.RabbitExchange, cfg.RabbitArchive)
	defer publisher.Close()

	relay := relayworker.New(
		store,
		publisher,
		log,
		cfg.WorkerID,
		cfg.BatchSize,
		cfg.PollInterval,
		cfg.ClaimStaleAfter,
		cfg.PublishTimeout,
		cfg.RetryBase,
		cfg.RetryMax,
	)
	go relay.Run(ctx)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"status":  "ok",
			"service": "outbox-relay",
		})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		checkCtx, checkCancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer checkCancel()

		if err := store.Ping(checkCtx); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"status":   "not_ready",
				"database": "unavailable",
			})
			return
		}
		if err := publisher.Ping(checkCtx); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"status":   "not_ready",
				"database": "ok",
				"rabbitmq": "unavailable",
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"status":   "ready",
			"database": "ok",
			"rabbitmq": "ok",
		})
	})

	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		log.Info(
			"outbox relay started",
			"port", cfg.Port,
			"worker_id", cfg.WorkerID,
			"batch_size", cfg.BatchSize,
		)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("outbox relay http server failed", "error", err)
			cancel()
		}
	}()

	<-ctx.Done()

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = server.Shutdown(shutdownCtx)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
