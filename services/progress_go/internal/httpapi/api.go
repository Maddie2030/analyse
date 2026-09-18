package httpapi

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"mreader/progress/internal/progress"
	"mreader/progress/internal/session"
	"mreader/progress/internal/store"
)

type API struct {
	store    *store.Store
	progress *progress.Service
	sessions *session.Service
	log      *slog.Logger
}

type openRequest struct {
	CommandID        string `json:"command_id"`
	ExpectedRevision *int64 `json:"expected_revision"`
}

type saveRequest struct {
	CommandID         string   `json:"command_id"`
	SessionGeneration *int64   `json:"session_generation"`
	CommandSequence   *int64   `json:"command_sequence"`
	LastPage          *int     `json:"last_page"`
	ScrollPosition    *float64 `json:"scroll_position"`
	Completed         *bool    `json:"completed"`
	CompletedPage     *int     `json:"completed_page"`
}

func decodeCommand(w http.ResponseWriter, r *http.Request, value any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
	dec.DisallowUnknownFields()
	if err := dec.Decode(value); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid reading command.")
		return false
	}
	if err := dec.Decode(&struct{}{}); err != io.EOF {
		writeError(w, http.StatusBadRequest, "Expected one reading command.")
		return false
	}
	return true
}

func validCommandID(id string) bool {
	if len(id) != 36 || id[8] != '-' || id[13] != '-' || id[18] != '-' || id[23] != '-' {
		return false
	}
	raw, err := hex.DecodeString(strings.ReplaceAll(id, "-", ""))
	return err == nil && len(raw) == 16 && id != "00000000-0000-0000-0000-000000000000"
}

func requireReadingAccount(w http.ResponseWriter, r *http.Request, userID string, required bool) bool {
	accountID := strings.TrimSpace(r.Header.Get("X-MReader-Account-ID"))
	if accountID == "" && !required {
		return true
	}
	if accountID == "" || !strings.EqualFold(accountID, userID) {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"detail": "Reading account no longer matches the authenticated session.",
			"code":   "account_mismatch",
		})
		return false
	}
	return true
}

func New(
	st *store.Store,
	progressService *progress.Service,
	sessions *session.Service,
	log *slog.Logger,
) *API {
	return &API{
		store:    st,
		progress: progressService,
		sessions: sessions,
		log:      log,
	}
}

func (a *API) Router() http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(a.requestLogger)
	r.Use(middleware.Recoverer)

	r.Get("/health", a.health)
	r.Get("/api/progress/history", a.history)
	r.Get(
		"/api/progress/series/{seriesSlug}/state",
		a.getSeriesState,
	)
	r.Get(
		"/api/progress/{seriesSlug}/{chapterSlug}",
		a.getProgress,
	)
	r.Post(
		"/api/progress/{seriesSlug}/{chapterSlug}/open",
		a.recordOpen,
	)
	r.Post(
		"/api/progress/{seriesSlug}/{chapterSlug}/commit",
		a.commitProgress,
	)

	return r
}

func (a *API) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "progress-go",
		"mode":    "primary",
	})
}

func (a *API) history(w http.ResponseWriter, r *http.Request) {
	sess, status, detail := a.sessions.RequireUser(r.Context(), r)
	if sess == nil {
		writeError(w, status, detail)
		return
	}
	if !requireReadingAccount(w, r, sess.UserID, false) {
		return
	}
	parse := func(name string, fallback, max int) (int, bool) {
		raw := strings.TrimSpace(r.URL.Query().Get(name))
		if raw == "" {
			return fallback, true
		}
		v, err := strconv.Atoi(raw)
		if err != nil || v < 0 || v > max {
			return 0, false
		}
		return v, true
	}
	offset, ok := parse("offset", 0, 1<<30)
	if !ok {
		writeError(w, http.StatusUnprocessableEntity, "Invalid offset.")
		return
	}
	limit, ok := parse("limit", 20, 100)
	if !ok || limit < 1 {
		writeError(w, http.StatusUnprocessableEntity, "Invalid limit.")
		return
	}
	items, err := a.store.History(r.Context(), sess.UserID, offset, limit)
	if err != nil {
		a.log.Error("reading history query failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (a *API) getSeriesState(w http.ResponseWriter, r *http.Request) {
	sess, status, detail := a.sessions.RequireUser(r.Context(), r)
	if sess == nil {
		writeError(w, status, detail)
		return
	}
	if !requireReadingAccount(w, r, sess.UserID, false) {
		return
	}
	seriesSlug := strings.TrimSpace(chi.URLParam(r, "seriesSlug"))
	state, err := a.store.GetSeriesState(r.Context(), sess.UserID, seriesSlug)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Series not found.")
		return
	}
	if err != nil {
		a.log.Error("series reading state query failed", "error", err, "series_slug", seriesSlug)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func (a *API) recordOpen(w http.ResponseWriter, r *http.Request) {
	sess, status, detail := a.sessions.RequireUser(r.Context(), r)
	if sess == nil {
		writeError(w, status, detail)
		return
	}
	if !requireReadingAccount(w, r, sess.UserID, true) {
		return
	}

	target, err := a.store.ResolveTarget(
		r.Context(),
		strings.TrimSpace(chi.URLParam(r, "seriesSlug")),
		strings.TrimSpace(chi.URLParam(r, "chapterSlug")),
	)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("history-open target query failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	var req openRequest
	if !decodeCommand(w, r, &req) {
		return
	}
	if !validCommandID(req.CommandID) || req.ExpectedRevision == nil || *req.ExpectedRevision < 0 || *req.ExpectedRevision >= store.MaxReadingOrder {
		writeError(w, http.StatusUnprocessableEntity, "command_id and expected_revision are required.")
		return
	}
	value, err := a.progress.RecordOpen(r.Context(), sess.UserID, target, store.OpenCommand{
		CommandID: strings.ToLower(req.CommandID), ExpectedRevision: *req.ExpectedRevision,
		RequestID: middleware.GetReqID(r.Context()), OperationID: strings.TrimSpace(r.Header.Get("X-MReader-Operation-ID")),
	})
	value.CommandID = req.CommandID
	a.writeCommandResult(w, r, value, err)

}

func (a *API) getProgress(w http.ResponseWriter, r *http.Request) {
	sess, status, detail := a.sessions.RequireUser(
		r.Context(),
		r,
	)
	if sess == nil {
		writeError(w, status, detail)
		return
	}
	if !requireReadingAccount(w, r, sess.UserID, false) {
		return
	}

	target, err := a.store.ResolveTarget(
		r.Context(),
		strings.TrimSpace(chi.URLParam(r, "seriesSlug")),
		strings.TrimSpace(chi.URLParam(r, "chapterSlug")),
	)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("progress target query failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	value, err := a.progress.Get(
		r.Context(),
		sess.UserID,
		target.SeriesID,
	)
	if err != nil {
		a.log.Error("progress read failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	if value == nil {
		writeJSON(w, http.StatusOK, map[string]any{
			"series_id":          target.SeriesID,
			"chapter_id":         target.ChapterID,
			"last_page":          1,
			"scroll_position":    0.0,
			"updated_at":         nil,
			"revision":           0,
			"last_opened_at":     nil,
			"session_generation": 0,
			"command_sequence":   0,
			"duplicate":          false,
			"code":               "accepted",
			"command_id":         "",
			"accepted":           true,
		})
		return
	}

	writeJSON(w, http.StatusOK, value)
}

func (a *API) commitProgress(w http.ResponseWriter, r *http.Request) {
	sess, status, detail := a.sessions.RequireUser(
		r.Context(),
		r,
	)
	if sess == nil {
		writeError(w, status, detail)
		return
	}
	if !requireReadingAccount(w, r, sess.UserID, true) {
		return
	}

	target, err := a.store.ResolveTarget(
		r.Context(),
		strings.TrimSpace(chi.URLParam(r, "seriesSlug")),
		strings.TrimSpace(chi.URLParam(r, "chapterSlug")),
	)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("progress target query failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	var req saveRequest
	if !decodeCommand(w, r, &req) {
		return
	}
	if !validCommandID(req.CommandID) || req.SessionGeneration == nil || req.CommandSequence == nil ||
		req.LastPage == nil || req.ScrollPosition == nil || req.Completed == nil || req.CompletedPage == nil {
		writeError(w, http.StatusUnprocessableEntity, "A complete reading command is required.")
		return
	}
	command := store.CommitCommand{
		CommandID: strings.ToLower(req.CommandID), RequestID: middleware.GetReqID(r.Context()),
		OperationID: strings.TrimSpace(r.Header.Get("X-MReader-Operation-ID")), SessionGeneration: *req.SessionGeneration,
		CommandSequence: *req.CommandSequence, LastPage: *req.LastPage,
		ScrollPosition: *req.ScrollPosition, Completed: *req.Completed, CompletedPage: *req.CompletedPage,
	}
	value, err := a.progress.Save(r.Context(), sess.UserID, target, command)
	value.CommandID = req.CommandID
	a.writeCommandResult(w, r, value, err)
}

func (a *API) writeCommandResult(w http.ResponseWriter, r *http.Request, value progress.Value, err error) {
	if errors.Is(err, store.ErrInvalidCommand) {
		writeError(w, http.StatusUnprocessableEntity, "Invalid reading session, sequence, checkpoint, or completion evidence.")
		return
	}
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("reading command not saved", "request_id", middleware.GetReqID(r.Context()), "error", err)
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"detail": "Progress storage unavailable.", "code": "progress_unsaved",
			"request_id": middleware.GetReqID(r.Context()), "retryable": true,
		})
		return
	}
	if !value.Accepted {
		a.log.Info("reading command rejected", "request_id", middleware.GetReqID(r.Context()),
			"code", value.Code, "revision", value.Revision, "session_generation", value.SessionGeneration)
	}
	writeJSON(w, http.StatusOK, value)
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (w *statusRecorder) WriteHeader(status int) {
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (a *API) requestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{
			ResponseWriter: w,
			status:         http.StatusOK,
		}

		next.ServeHTTP(rec, r)

		a.log.Info(
			"http request",
			"request_id", middleware.GetReqID(r.Context()),
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
