package main

import (
	"context"
	"encoding/json"
	"hash/fnv"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"mreader/realtime/internal/config"
	"mreader/realtime/internal/hub"
	"mreader/realtime/internal/session"
	"mreader/realtime/internal/sources"
)

const sessionInvalidCloseCode = 4001

type clientCommand struct {
	Type      string  `json:"type"`
	SeriesID  string  `json:"series_id"`
	ChapterID *string `json:"chapter_id"`
}

func main() {
	cfg := config.Load()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	poolCfg, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		log.Error("invalid realtime database url", "error", err)
		os.Exit(1)
	}
	poolCfg.MaxConns = cfg.DBMaxConns
	db, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		log.Error("realtime database pool failed", "error", err)
		os.Exit(1)
	}
	defer db.Close()
	if err := db.Ping(ctx); err != nil {
		log.Error("realtime database ping failed", "error", err)
		os.Exit(1)
	}

	redisOptions, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		log.Error("invalid realtime redis url", "error", err)
		os.Exit(1)
	}
	redisOptions.PoolSize = cfg.RedisPoolSize
	redisOptions.MinIdleConns = 1
	redisOptions.PoolTimeout = 3 * time.Second
	redisClient := redis.NewClient(redisOptions)
	defer redisClient.Close()
	if err := redisClient.Ping(ctx).Err(); err != nil {
		log.Error("realtime redis ping failed", "error", err)
		os.Exit(1)
	}

	realtimeHub := hub.New(log)
	sessionService := session.New(redisClient, cfg.SessionCookie)
	rabbitSource := sources.NewRabbitSource(cfg.RabbitURL, cfg.EventsExchange, cfg.ReconnectDelay, db, realtimeHub, log)
	commentSource := sources.NewCommentSource(redisClient, realtimeHub, log)
	defer rabbitSource.Close()
	go rabbitSource.Run(ctx)
	go commentSource.Run(ctx)

	upgrader := websocket.Upgrader{
		HandshakeTimeout: 5 * time.Second,
		CheckOrigin:      sameOrigin,
		// Realtime payloads are tiny JSON signals. Per-message compression costs
		// more CPU than it saves on this constrained profile.
		EnableCompression: false,
	}

	websocketHandler := func(w http.ResponseWriter, r *http.Request) {
		sess := sessionService.OptionalFromRequest(r.Context(), r)
		userID := ""
		sessionID := ""
		if sess != nil {
			userID = sess.UserID
			sessionID = sess.SessionID
		}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Warn("websocket upgrade failed", "error", err)
			return
		}
		client := hub.NewClient(conn, userID, sessionID)
		realtimeHub.Register(client)
		log.Info("realtime client connected", "authenticated", userID != "")
		go writePump(cfg, realtimeHub, sessionService, log, client)
		readPump(cfg, realtimeHub, client)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/realtime/ws", websocketHandler)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		clients, users, commentSubscriptions := realtimeHub.Counts()
		writeJSON(w, http.StatusOK, map[string]any{
			"status": "ok", "service": "realtime-go", "clients": clients,
			"authenticated_users": users, "comment_subscriptions": commentSubscriptions,
		})
	})
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		checkCtx, checkCancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer checkCancel()
		dbOK := db.Ping(checkCtx) == nil
		redisOK := redisClient.Ping(checkCtx).Err() == nil
		rabbitOK := rabbitSource.Ready()
		commentsOK := commentSource.Ready()
		if !dbOK || !redisOK || !rabbitOK || !commentsOK {
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{
				"status": "not_ready", "database": dbOK, "redis": redisOK,
				"rabbitmq": rabbitOK, "comment_pubsub": commentsOK,
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"status": "ready", "database": "ok", "redis": "ok",
			"rabbitmq": "ok", "comment_pubsub": "ok",
		})
	})

	server := &http.Server{
		Addr: ":" + cfg.Port, Handler: mux, ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second,
	}
	go func() {
		log.Info("realtime service started", "port", cfg.Port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("realtime http server failed", "error", err)
			cancel()
		}
	}()

	<-ctx.Done()
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	_ = server.Shutdown(shutdownCtx)
}

func readPump(cfg config.Config, h *hub.Hub, client *hub.Client) {
	defer h.Unregister(client)
	client.Conn.SetReadLimit(cfg.MaxMessageBytes)
	_ = client.Conn.SetReadDeadline(time.Now().Add(cfg.PongWait))
	client.Conn.SetPongHandler(func(string) error {
		return client.Conn.SetReadDeadline(time.Now().Add(cfg.PongWait))
	})
	for {
		_, body, err := client.Conn.ReadMessage()
		if err != nil {
			return
		}
		var command clientCommand
		if json.Unmarshal(body, &command) != nil {
			continue
		}
		switch command.Type {
		case "subscribe.comments":
			if !validUUID(command.SeriesID) {
				continue
			}
			chapter := "series"
			if command.ChapterID != nil {
				if !validUUID(*command.ChapterID) {
					continue
				}
				chapter = *command.ChapterID
			}
			h.SubscribeComment(client, command.SeriesID+":"+chapter)
		case "unsubscribe.comments":
			if !validUUID(command.SeriesID) {
				continue
			}
			chapter := "series"
			if command.ChapterID != nil {
				if !validUUID(*command.ChapterID) {
					continue
				}
				chapter = *command.ChapterID
			}
			h.UnsubscribeComment(client, command.SeriesID+":"+chapter)
		case "ping":
			select {
			case client.Send <- []byte(`{"type":"pong"}`):
			default:
			}
		}
	}
}

func sessionRecheckDelay(base time.Duration, sessionID string) time.Duration {
	if base <= 0 || sessionID == "" {
		return base
	}
	// Stable +/-10% jitter per session spreads checks across the interval while
	// preserving revocation timing. It also avoids synchronized Redis bursts
	// after a realtime pod restart.
	span := base / 5
	if span <= 0 {
		return base
	}
	h := fnv.New32a()
	_, _ = h.Write([]byte(sessionID))
	offset := time.Duration(uint64(h.Sum32())%uint64(span+1)) - span/2
	return base + offset
}

func writePump(cfg config.Config, h *hub.Hub, sessions *session.Service, log *slog.Logger, client *hub.Client) {
	pingTicker := time.NewTicker(cfg.PingPeriod)
	defer pingTicker.Stop()

	var sessionTimer *time.Timer
	var sessionChecks <-chan time.Time
	if client.UserID != "" && client.SessionID != "" {
		sessionTimer = time.NewTimer(sessionRecheckDelay(cfg.SessionRecheck, client.SessionID))
		sessionChecks = sessionTimer.C
		defer sessionTimer.Stop()
	}
	defer h.Unregister(client)
	ready, _ := json.Marshal(map[string]any{"type": "ready", "authenticated": client.UserID != ""})
	select {
	case client.Send <- ready:
	default:
		return
	}
	for {
		select {
		case <-client.Done():
			return
		case message := <-client.Send:
			_ = client.Conn.SetWriteDeadline(time.Now().Add(cfg.WriteTimeout))
			if err := client.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
				return
			}
		case <-pingTicker.C:
			_ = client.Conn.SetWriteDeadline(time.Now().Add(cfg.WriteTimeout))
			if err := client.Conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		case <-sessionChecks:
			checkCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			valid, err := sessions.Validate(checkCtx, client.SessionID, client.UserID)
			cancel()
			if sessionTimer != nil {
				sessionTimer.Reset(sessionRecheckDelay(cfg.SessionRecheck, client.SessionID))
			}
			if err != nil {
				log.Warn("realtime session revalidation deferred", "error", err)
				continue
			}
			if !valid {
				_ = client.Conn.SetWriteDeadline(time.Now().Add(cfg.WriteTimeout))
				_ = client.Conn.WriteControl(
					websocket.CloseMessage,
					websocket.FormatCloseMessage(sessionInvalidCloseCode, "session invalidated"),
					time.Now().Add(cfg.WriteTimeout),
				)
				return
			}
		}
	}
}

func sameOrigin(r *http.Request) bool {
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" {
		return true
	}
	parsed, err := url.Parse(origin)
	if err != nil {
		return false
	}
	return strings.EqualFold(parsed.Host, r.Host)
}

func validUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for i, r := range value {
		switch i {
		case 8, 13, 18, 23:
			if r != '-' {
				return false
			}
		default:
			if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f') || (r >= 'A' && r <= 'F')) {
				return false
			}
		}
	}
	return true
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
