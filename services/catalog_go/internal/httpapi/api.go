package httpapi

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"log/slog"
	"math"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"mreader/catalog/internal/cache"
	"mreader/catalog/internal/model"
	"mreader/catalog/internal/session"
	"mreader/catalog/internal/store"
)

type API struct {
	store         *store.Store
	sessions      *session.Service
	cache         *cache.Service
	enableWrites  bool
	internalToken string
	log           *slog.Logger
	canary        *canaryMetrics
}

func New(st *store.Store, sess *session.Service, cacheSvc *cache.Service, enableWrites bool, internalToken string, log *slog.Logger) *API {
	return &API{store: st, sessions: sess, cache: cacheSvc, enableWrites: enableWrites, internalToken: strings.TrimSpace(internalToken), log: log, canary: newCanaryMetrics()}
}

func (a *API) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(chimw.RequestID, chimw.RealIP, a.requestLogger, chimw.Recoverer, a.canaryMiddleware)
	r.Get("/health", a.health)
	r.Get("/internal/canary/stats", a.canaryStats)
	r.Post("/internal/v1/catalog/publications", a.commitPublication)
	r.Post("/internal/v1/catalog/series", a.createInternalSeries)
	r.Put("/internal/v1/catalog/series/{seriesID}/cover", a.setInternalSeriesCover)
	r.Route("/api/catalog", func(r chi.Router) {
		r.Get("/series", a.listSeries)
		r.Get("/genres", a.genres)
		r.Get("/tags", a.tags)
		r.Get("/discover", a.discovery)
		r.Get("/trending", a.trending)
		r.Get("/curation", a.curation)
		r.Get("/admin/stats", a.adminStats)
		r.Get("/admin/curation", a.adminCuration)
		r.Post("/admin/editor-picks", a.createEditorPick)
		r.Put("/admin/editor-picks/{id}", a.updateEditorPick)
		r.Delete("/admin/editor-picks/{id}", a.deleteEditorPick)
		r.Post("/admin/announcements", a.createAnnouncement)
		r.Put("/admin/announcements/{id}", a.updateAnnouncement)
		r.Delete("/admin/announcements/{id}", a.deleteAnnouncement)
		r.Get("/series/{slug}", a.seriesDetail)
		r.Get("/series/{slug}/chapters/{chapterSlug}", a.chapterDetail)
		r.Post("/series", a.createSeries)
		r.Put("/series/{seriesID}", a.updateSeries)
		r.Delete("/series/{seriesID}", a.deleteSeries)
		r.Post("/series/{seriesID}/chapters", a.createChapter)
		r.Put("/series/{seriesID}/chapters/{chapterID}", a.updateChapter)
		r.Delete("/series/{seriesID}/chapters/{chapterID}", a.deleteChapter)
		r.Post("/series/{seriesID}/chapters/{chapterID}/publish", a.publishChapter)
	})
	return r
}

func (a *API) requireInternalWrite(w http.ResponseWriter, r *http.Request) bool {
	providedToken := strings.TrimSpace(r.Header.Get("X-MReader-Internal-Token"))
	if a.internalToken == "" {
		writeErrorJSON(w, http.StatusServiceUnavailable, "internal_transport_unconfigured", "Internal transport is not configured")
		return false
	}
	if providedToken == "" || subtle.ConstantTimeCompare([]byte(providedToken), []byte(a.internalToken)) != 1 {
		writeErrorJSON(w, http.StatusUnauthorized, "invalid_internal_token", "Invalid internal workload credential")
		return false
	}
	actorID := strings.TrimSpace(r.Header.Get("X-MReader-Requesting-Actor-ID"))
	if actorID == "" || !uuidPattern.MatchString(actorID) {
		writeErrorJSON(w, http.StatusUnauthorized, "missing_requesting_actor", "Missing or invalid requesting actor")
		return false
	}
	authorized, err := a.store.IsActiveAdmin(r.Context(), actorID)
	if err != nil {
		a.internal(w, err)
		return false
	}
	if !authorized {
		writeErrorJSON(w, http.StatusForbidden, "requesting_actor_unauthorized", "Requesting actor is not an active admin")
		return false
	}
	if !a.enableWrites {
		writeErrorJSON(w, http.StatusServiceUnavailable, "catalog_writes_disabled", "Catalog writes are disabled")
		return false
	}
	return true
}

func (a *API) createSeriesMutation(w http.ResponseWriter, r *http.Request) {
	var body model.SeriesCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if body.Status == "" {
		body.Status = "ongoing"
	}
	body.TagNames = normalizeTagNames(body.TagNames)
	if body.Title == "" || !utf8.ValidString(body.Title) {
		bodyValidation(w, "title", "Input should be a valid string")
		return
	}
	if !slugPattern.MatchString(body.Slug) {
		bodyValidation(w, "slug", "Value error, Slug must be lowercase kebab-case.")
		return
	}
	if !validSeriesStatus(body.Status) {
		bodyValidation(w, "status", "Input should be 'ongoing', 'completed', 'hiatus' or 'cancelled'")
		return
	}
	if !validTagNames(body.GenreNames) {
		bodyValidation(w, "genre_names", "Genres must be valid UTF-8 names up to 100 characters; maximum 50 genres")
		return
	}
	if !validTagNames(body.TagNames) {
		bodyValidation(w, "tag_names", "Tags must be valid UTF-8 names up to 100 characters; maximum 50 tags")
		return
	}
	x, err := a.store.CreateSeries(r.Context(), body)
	if errors.Is(err, store.ErrConflict) {
		detail(w, http.StatusConflict, "Slug already exists.")
		return
	}
	if errors.Is(err, store.ErrInvalidReference) {
		detail(w, http.StatusUnprocessableEntity, "One or more genre/tag references do not exist.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	if err := a.cache.InvalidateScope(r.Context(), "series"); err != nil {
		a.log.Warn("series cache invalidation failed", "error", err)
	}
	if err := a.cache.Delete(r.Context(), "genres", "all"); err != nil {
		a.log.Warn("genres cache invalidation failed", "error", err)
	}
	if err := a.cache.Delete(r.Context(), "tags", "all"); err != nil {
		a.log.Warn("tags cache invalidation failed", "error", err)
	}
	writeJSON(w, http.StatusCreated, x)
}

func (a *API) createSeriesWithGuard(
	w http.ResponseWriter,
	r *http.Request,
	guard func(http.ResponseWriter, *http.Request) bool,
) {
	if guard(w, r) {
		a.createSeriesMutation(w, r)
	}
}

func (a *API) createInternalSeries(w http.ResponseWriter, r *http.Request) {
	a.createSeriesWithGuard(w, r, a.requireInternalWrite)
}

func (a *API) setSeriesCoverMutation(w http.ResponseWriter, r *http.Request) {
	seriesID := chi.URLParam(r, "seriesID")
	if !uuidPattern.MatchString(seriesID) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	var body struct {
		CoverImagePath  *string `json:"cover_image_path"`
		MediaGeneration int64   `json:"media_generation"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if body.CoverImagePath != nil {
		trimmed := strings.TrimSpace(*body.CoverImagePath)
		if trimmed == "" || strings.Contains(trimmed, "..") || strings.HasPrefix(trimmed, "/") {
			bodyValidation(w, "cover_image_path", "Cover image path must be a non-empty relative object path")
			return
		}
		if body.MediaGeneration < 1 {
			bodyValidation(w, "media_generation", "Media generation must be positive for a cover attachment")
			return
		}
		body.CoverImagePath = &trimmed
	} else {
		body.MediaGeneration = 0
	}
	x, err := a.store.SetSeriesCover(r.Context(), seriesID, body.CoverImagePath, body.MediaGeneration, store.EventMetadata{
		RequestID:   chimw.GetReqID(r.Context()),
		OperationID: strings.TrimSpace(r.Header.Get("X-MReader-Operation-ID")),
	})
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	if err := a.cache.InvalidateScope(r.Context(), "series"); err != nil {
		a.log.Warn("series cache invalidation failed", "error", err)
	}
	writeJSON(w, http.StatusOK, x)
}

func (a *API) setInternalSeriesCover(w http.ResponseWriter, r *http.Request) {
	if a.requireInternalWrite(w, r) {
		a.setSeriesCoverMutation(w, r)
	}
}

const (
	catalogTaxonomyCacheTTL = 30 * time.Second
	catalogHotReadCacheTTL  = 10 * time.Second
	catalogDetailCacheTTL   = 5 * time.Second
)

func normalizedCacheKey(prefix string, value any) string {
	body, err := json.Marshal(value)
	if err != nil {
		return prefix
	}
	return prefix + ":" + string(body)
}

func (a *API) loadCacheableJSON(
	r *http.Request,
	scope string,
	key string,
	ttl time.Duration,
	loader func() (any, error),
) ([]byte, string, error) {
	return a.cache.LoadLocal(r.Context(), scope, key, ttl, func() ([]byte, error) {
		value, err := loader()
		if err != nil {
			return nil, err
		}
		body, err := json.Marshal(value)
		if err != nil {
			return nil, err
		}
		return append(body, '\n'), nil
	})
}

func writeCachedJSONBody(w http.ResponseWriter, body []byte, state string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-MReader-Local-Cache", state)
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (a *API) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": "catalog-go", "mode": "shadow", "writes_enabled": a.enableWrites})
}

func writeErrorJSON(w http.ResponseWriter, status int, code, message string) {
	body := map[string]string{"detail": message}
	if code != "" {
		body["code"] = code
	}
	writeJSON(w, status, body)
}

func publicationDomainError(w http.ResponseWriter, status int, code, message string) {
	writeErrorJSON(w, status, code, message)
}

func (a *API) commitPublication(w http.ResponseWriter, r *http.Request) {
	if !a.requireInternalWrite(w, r) {
		return
	}
	var command model.PublicationCommand
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&command); err != nil {
		publicationDomainError(w, http.StatusBadRequest, "invalid_publication_command", "Invalid publication command")
		return
	}
	requestingActor := strings.TrimSpace(r.Header.Get("X-MReader-Requesting-Actor-ID"))
	if requestingActor == "" || requestingActor != command.ActorID {
		publicationDomainError(w, http.StatusForbidden, "publication_actor_mismatch", "Requesting actor does not match publication command")
		return
	}
	command.RequestID = chimw.GetReqID(r.Context())
	receipt, err := a.store.CommitPublication(r.Context(), command)
	switch {
	case err == nil:
		a.invalidateChapterCaches(r)
		writeJSON(w, http.StatusOK, receipt)
	case errors.Is(err, store.ErrIdempotencyConflict):
		publicationDomainError(w, http.StatusConflict, "idempotency_conflict", err.Error())
	case errors.Is(err, store.ErrStaleCatalogRevision):
		publicationDomainError(w, http.StatusConflict, "stale_catalog_revision", err.Error())
	case errors.Is(err, store.ErrMediaEvidenceMismatch):
		publicationDomainError(w, http.StatusConflict, "media_evidence_mismatch", err.Error())
	case errors.Is(err, store.ErrPublicationActorUnauthorized):
		publicationDomainError(w, http.StatusForbidden, "publication_actor_unauthorized", err.Error())
	case errors.Is(err, store.ErrStaleIngestionSourceRevision):
		publicationDomainError(w, http.StatusConflict, "stale_ingestion_source_revision", err.Error())
	case errors.Is(err, store.ErrStaleIngestionGeneration):
		publicationDomainError(w, http.StatusConflict, "stale_ingestion_generation", err.Error())
	case errors.Is(err, store.ErrIngestionCancelled):
		publicationDomainError(w, http.StatusConflict, "ingestion_cancelled", err.Error())
	case errors.Is(err, store.ErrIngestionNotRunning):
		publicationDomainError(w, http.StatusConflict, "ingestion_not_running", err.Error())
	case errors.Is(err, store.ErrConflict):
		publicationDomainError(w, http.StatusConflict, "publication_conflict", err.Error())
	case errors.Is(err, store.ErrNotFound):
		publicationDomainError(w, http.StatusNotFound, "publication_target_not_found", err.Error())
	default:
		a.internal(w, err)
	}
}

func (a *API) genres(w http.ResponseWriter, r *http.Request) {
	body, state, err := a.loadCacheableJSON(r, "genres", "all", catalogTaxonomyCacheTTL, func() (any, error) {
		return a.store.Genres(r.Context())
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}
func (a *API) tags(w http.ResponseWriter, r *http.Request) {
	body, state, err := a.loadCacheableJSON(r, "tags", "all", catalogTaxonomyCacheTTL, func() (any, error) {
		return a.store.Tags(r.Context())
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}
func (a *API) discovery(w http.ResponseWriter, r *http.Request) {
	body, state, err := a.loadCacheableJSON(r, "series", "discovery", catalogHotReadCacheTTL, func() (any, error) {
		return a.store.Discovery(r.Context())
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}

func (a *API) trending(w http.ResponseWriter, r *http.Request) {
	window := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("window")))
	if window == "" {
		window = "24h"
	}
	hours := 0
	switch window {
	case "24h":
		hours = 24
	case "7d":
		hours = 24 * 7
	case "30d":
		hours = 24 * 30
	default:
		validation(w, "window")
		return
	}
	limit, ok := parseBounded(r.URL.Query().Get("limit"), 10, 1, 25)
	if !ok {
		validation(w, "limit")
		return
	}
	cacheKey := "trending:" + window + ":" + strconv.Itoa(limit)
	body, state, err := a.loadCacheableJSON(r, "series", cacheKey, catalogHotReadCacheTTL, func() (any, error) {
		items, err := a.store.Trending(r.Context(), hours, limit)
		if err != nil {
			return nil, err
		}
		return model.TrendingResponse{Window: window, GeneratedAt: time.Now().UTC(), Items: items}, nil
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}

func (a *API) curation(w http.ResponseWriter, r *http.Request) {
	body, state, err := a.loadCacheableJSON(r, "curation", "public", catalogHotReadCacheTTL, func() (any, error) {
		return a.store.PublicCuration(r.Context())
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}

func (a *API) adminCuration(w http.ResponseWriter, r *http.Request) {
	_, statusCode, message := a.sessions.RequireAdmin(r.Context(), r)
	if statusCode != 0 {
		detail(w, statusCode, message)
		return
	}
	x, err := a.store.AdminCuration(r.Context())
	if err != nil {
		a.internal(w, err)
		return
	}
	writeJSON(w, http.StatusOK, x)
}

func validateSchedule(startsAt, endsAt *time.Time) bool {
	return startsAt == nil || endsAt == nil || endsAt.After(*startsAt)
}

func cleanOptional(value *string, max int) (*string, bool) {
	if value == nil {
		return nil, true
	}
	trimmed := strings.TrimSpace(*value)
	if trimmed == "" {
		return nil, true
	}
	if utf8.RuneCountInString(trimmed) > max {
		return nil, false
	}
	return &trimmed, true
}

func safeCurationURL(value *string) (*string, bool) {
	clean, ok := cleanOptional(value, 1000)
	if !ok || clean == nil {
		return clean, ok
	}
	if (strings.HasPrefix(*clean, "/") && !strings.HasPrefix(*clean, "//")) || strings.HasPrefix(*clean, "https://") {
		return clean, true
	}
	return nil, false
}

func (a *API) createEditorPick(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	var body model.EditorPickUpsertRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if !uuidPattern.MatchString(body.SeriesID) {
		bodyValidation(w, "series_id", "Input should be a valid UUID")
		return
	}
	if body.Position < 0 {
		bodyValidation(w, "position", "Input should be greater than or equal to 0")
		return
	}
	var ok bool
	body.Label, ok = cleanOptional(body.Label, 80)
	if !ok {
		bodyValidation(w, "label", "String should have at most 80 characters")
		return
	}
	body.Note, ok = cleanOptional(body.Note, 280)
	if !ok {
		bodyValidation(w, "note", "String should have at most 280 characters")
		return
	}
	if !validateSchedule(body.StartsAt, body.EndsAt) {
		bodyValidation(w, "ends_at", "End time must be after start time")
		return
	}
	x, err := a.store.CreateEditorPick(r.Context(), body, "")
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	if errors.Is(err, store.ErrConflict) {
		detail(w, http.StatusConflict, "Series is already an Editor Pick.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	writeJSON(w, http.StatusCreated, x)
}

func (a *API) updateEditorPick(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	id := chi.URLParam(r, "id")
	if !uuidPattern.MatchString(id) {
		detail(w, http.StatusNotFound, "Editor Pick not found.")
		return
	}
	var body model.EditorPickUpsertRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if !uuidPattern.MatchString(body.SeriesID) {
		bodyValidation(w, "series_id", "Input should be a valid UUID")
		return
	}
	if body.Position < 0 {
		bodyValidation(w, "position", "Input should be greater than or equal to 0")
		return
	}
	var ok bool
	body.Label, ok = cleanOptional(body.Label, 80)
	if !ok {
		bodyValidation(w, "label", "String should have at most 80 characters")
		return
	}
	body.Note, ok = cleanOptional(body.Note, 280)
	if !ok {
		bodyValidation(w, "note", "String should have at most 280 characters")
		return
	}
	if !validateSchedule(body.StartsAt, body.EndsAt) {
		bodyValidation(w, "ends_at", "End time must be after start time")
		return
	}
	x, err := a.store.UpdateEditorPick(r.Context(), id, body)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Editor Pick or series not found.")
		return
	}
	if errors.Is(err, store.ErrConflict) {
		detail(w, http.StatusConflict, "Series is already an Editor Pick.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	writeJSON(w, http.StatusOK, x)
}

func (a *API) deleteEditorPick(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	id := chi.URLParam(r, "id")
	if !uuidPattern.MatchString(id) {
		detail(w, http.StatusNotFound, "Editor Pick not found.")
		return
	}
	err := a.store.DeleteEditorPick(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Editor Pick not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	w.WriteHeader(http.StatusNoContent)
}

func validAnnouncementTone(value string) bool {
	return value == "info" || value == "success" || value == "warning" || value == "critical"
}

func validateAnnouncementBody(body *model.AnnouncementUpsertRequest) (string, string, bool) {
	title := strings.TrimSpace(body.Title)
	text := strings.TrimSpace(body.Body)
	if title == "" || utf8.RuneCountInString(title) > 120 {
		return "title", "Title is required and must have at most 120 characters", false
	}
	if text == "" || utf8.RuneCountInString(text) > 1000 {
		return "body", "Body is required and must have at most 1000 characters", false
	}
	body.Title = title
	body.Body = text
	if body.Tone == "" {
		body.Tone = "info"
	}
	if !validAnnouncementTone(body.Tone) {
		return "tone", "Input should be 'info', 'success', 'warning' or 'critical'", false
	}
	if body.Position < 0 {
		return "position", "Input should be greater than or equal to 0", false
	}
	var ok bool
	body.LinkURL, ok = safeCurationURL(body.LinkURL)
	if !ok {
		return "link_url", "Link must be an internal /path or an https:// URL", false
	}
	body.LinkLabel, ok = cleanOptional(body.LinkLabel, 80)
	if !ok {
		return "link_label", "String should have at most 80 characters", false
	}
	if !validateSchedule(body.StartsAt, body.EndsAt) {
		return "ends_at", "End time must be after start time", false
	}
	return "", "", true
}

func (a *API) createAnnouncement(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	var body model.AnnouncementUpsertRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	field, message, ok := validateAnnouncementBody(&body)
	if !ok {
		bodyValidation(w, field, message)
		return
	}
	x, err := a.store.CreateAnnouncement(r.Context(), body, "")
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	writeJSON(w, http.StatusCreated, x)
}

func (a *API) updateAnnouncement(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	id := chi.URLParam(r, "id")
	if !uuidPattern.MatchString(id) {
		detail(w, http.StatusNotFound, "Announcement not found.")
		return
	}
	var body model.AnnouncementUpsertRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	field, message, ok := validateAnnouncementBody(&body)
	if !ok {
		bodyValidation(w, field, message)
		return
	}
	x, err := a.store.UpdateAnnouncement(r.Context(), id, body)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Announcement not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	writeJSON(w, http.StatusOK, x)
}

func (a *API) deleteAnnouncement(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	id := chi.URLParam(r, "id")
	if !uuidPattern.MatchString(id) {
		detail(w, http.StatusNotFound, "Announcement not found.")
		return
	}
	err := a.store.DeleteAnnouncement(r.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Announcement not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateCurationCaches(r)
	w.WriteHeader(http.StatusNoContent)
}

func (a *API) adminStats(w http.ResponseWriter, r *http.Request) {
	_, statusCode, message := a.sessions.RequireAdmin(r.Context(), r)
	if statusCode != 0 {
		detail(w, statusCode, message)
		return
	}
	x, err := a.store.AdminStats(r.Context())
	if err != nil {
		a.internal(w, err)
		return
	}
	writeJSON(w, http.StatusOK, x)
}

func parseIDList(raw string) ([]int, bool) {
	if strings.TrimSpace(raw) == "" {
		return nil, true
	}

	seen := map[int]struct{}{}
	out := []int{}

	for _, part := range strings.Split(raw, ",") {
		value := strings.TrimSpace(part)
		if value == "" {
			continue
		}

		n, err := strconv.Atoi(value)
		if err != nil || n <= 0 {
			return nil, false
		}

		if _, exists := seen[n]; exists {
			continue
		}

		seen[n] = struct{}{}
		out = append(out, n)
	}

	return out, true
}

func (a *API) listSeries(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	offset, ok := parseBounded(q.Get("offset"), 0, 0, 1<<30)
	if !ok {
		validation(w, "offset")
		return
	}
	limit, ok := parseBounded(q.Get("limit"), 20, 1, 100)
	if !ok {
		validation(w, "limit")
		return
	}
	f := store.SeriesFilter{
		Search: q.Get("search"),
		Status: q.Get("status"),
		Offset: offset,
		Limit:  limit,
	}

	sortMode := strings.ToLower(strings.TrimSpace(q.Get("sort")))
	if sortMode == "" {
		if strings.TrimSpace(f.Search) != "" {
			sortMode = "relevance"
		} else {
			sortMode = "updated"
		}
	}
	switch sortMode {
	case "relevance", "updated", "newest", "title", "rating", "popular":
		f.Sort = sortMode
	default:
		validation(w, "sort")
		return
	}

	genreIDs, ok := parseIDList(q.Get("genre"))
	if !ok {
		validation(w, "genre")
		return
	}
	f.GenreIDs = genreIDs

	tagIDs, ok := parseIDList(q.Get("tag"))
	if !ok {
		validation(w, "tag")
		return
	}
	f.TagIDs = tagIDs

	if raw := strings.TrimSpace(q.Get("min_rating")); raw != "" {
		value, err := strconv.ParseFloat(raw, 64)
		if err != nil || value < 1 || value > 5 {
			validation(w, "min_rating")
			return
		}
		f.MinRating = &value
	}

	cacheKey := normalizedCacheKey("series-list", f)
	body, state, err := a.loadCacheableJSON(r, "series", cacheKey, catalogHotReadCacheTTL, func() (any, error) {
		return a.store.SeriesList(r.Context(), f)
	})
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}
func (a *API) seriesDetail(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	offset, ok := parseBounded(q.Get("chapter_offset"), 0, 0, 1<<30)
	if !ok {
		validation(w, "chapter_offset")
		return
	}
	limit, ok := parseBounded(q.Get("chapter_limit"), 20, 1, 100)
	if !ok {
		validation(w, "chapter_limit")
		return
	}
	sess := a.sessions.OptionalFromRequest(r.Context(), r)
	admin := sess != nil && sess.Role == "admin"
	chapterSearch := strings.TrimSpace(q.Get("chapter_search"))
	if admin {
		x, err := a.store.SeriesDetail(r.Context(), chi.URLParam(r, "slug"), true, offset, limit, chapterSearch)
		if errors.Is(err, store.ErrNotFound) {
			detail(w, 404, "Series not found.")
			return
		}
		if err != nil {
			a.internal(w, err)
			return
		}
		writeJSON(w, http.StatusOK, x)
		return
	}
	cacheKey := normalizedCacheKey("series-detail", struct {
		Slug   string `json:"slug"`
		Offset int    `json:"offset"`
		Limit  int    `json:"limit"`
		Search string `json:"search"`
	}{chi.URLParam(r, "slug"), offset, limit, chapterSearch})
	body, state, err := a.loadCacheableJSON(r, "series", cacheKey, catalogDetailCacheTTL, func() (any, error) {
		return a.store.SeriesDetail(r.Context(), chi.URLParam(r, "slug"), false, offset, limit, chapterSearch)
	})
	if errors.Is(err, store.ErrNotFound) {
		detail(w, 404, "Series not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}
func (a *API) chapterDetail(w http.ResponseWriter, r *http.Request) {
	cacheKey := "chapter-detail:" + chi.URLParam(r, "slug") + ":" + chi.URLParam(r, "chapterSlug")
	body, state, err := a.loadCacheableJSON(r, "chapter", cacheKey, catalogDetailCacheTTL, func() (any, error) {
		return a.store.ChapterDetail(r.Context(), chi.URLParam(r, "slug"), chi.URLParam(r, "chapterSlug"))
	})
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			if strings.HasPrefix(err.Error(), "series:") {
				detail(w, 404, "Series not found.")
			} else {
				detail(w, 404, "Chapter not found.")
			}
			return
		}
		a.internal(w, err)
		return
	}
	writeCachedJSONBody(w, body, state)
}

var slugPattern = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

func (a *API) createSeries(w http.ResponseWriter, r *http.Request) {
	a.createSeriesWithGuard(w, r, a.requireShadowWrite)
}

func (a *API) updateSeries(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	seriesID := chi.URLParam(r, "seriesID")
	if !uuidPattern.MatchString(seriesID) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	var body model.SeriesUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if body.Title != nil {
		trimmed := strings.TrimSpace(*body.Title)
		if trimmed == "" || !utf8.ValidString(trimmed) {
			bodyValidation(w, "title", "Input should be a non-empty valid string")
			return
		}
		body.Title = &trimmed
	}
	if body.Status != nil && !validSeriesStatus(*body.Status) {
		bodyValidation(w, "status", "Input should be 'ongoing', 'completed', 'hiatus' or 'cancelled'")
		return
	}
	if body.TagNames != nil && body.TagIDs != nil {
		bodyValidation(w, "tags", "Provide either tag_names or tag_ids, not both")
		return
	}
	if body.TagNames != nil && !validTagNames(*body.TagNames) {
		bodyValidation(w, "tag_names", "Tags must be valid UTF-8 names up to 100 characters; maximum 50 tags")
		return
	}
	x, err := a.store.UpdateSeries(r.Context(), seriesID, body, store.EventMetadata{
		RequestID:   chimw.GetReqID(r.Context()),
		OperationID: strings.TrimSpace(r.Header.Get("X-MReader-Operation-ID")),
	})
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	if errors.Is(err, store.ErrInvalidReference) {
		detail(w, http.StatusUnprocessableEntity, "One or more genre/tag references do not exist.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	if err := a.cache.InvalidateScope(r.Context(), "series"); err != nil {
		a.log.Warn("series cache invalidation failed", "error", err)
	}
	if body.GenreIDs != nil {
		if err := a.cache.Delete(r.Context(), "genres", "all"); err != nil {
			a.log.Warn("genres cache invalidation failed", "error", err)
		}
	}
	if body.TagNames != nil || body.TagIDs != nil {
		if err := a.cache.Delete(r.Context(), "tags", "all"); err != nil {
			a.log.Warn("tags cache invalidation failed", "error", err)
		}
	}
	a.invalidateCurationCaches(r)
	if body.Status != nil || body.TagNames != nil || body.TagIDs != nil {
		a.log.Info(
			"admin series metadata request applied",
			"series_id", seriesID,
			"request_id", chimw.GetReqID(r.Context()),
			"status", x.Status,
			"tag_count", len(x.Tags),
		)
	}
	writeJSON(w, http.StatusOK, x)
}

func (a *API) deleteSeries(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	seriesID := chi.URLParam(r, "seriesID")
	if !uuidPattern.MatchString(seriesID) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	cleanupJobID, err := a.store.DeleteSeries(r.Context(), seriesID)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	if err := a.cache.InvalidateScope(r.Context(), "series"); err != nil {
		a.log.Warn("series cache invalidation failed", "error", err)
	}
	if err := a.cache.Delete(r.Context(), "genres", "all"); err != nil {
		a.log.Warn("genres cache invalidation failed", "error", err)
	}
	if err := a.cache.Delete(r.Context(), "tags", "all"); err != nil {
		a.log.Warn("tags cache invalidation failed", "error", err)
	}
	a.invalidateCurationCaches(r)
	writeJSON(w, http.StatusAccepted, map[string]any{
		"catalog_removed": true,
		"storage_cleanup": "queued",
		"job_id":          cleanupJobID,
	})
}

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$`)

func (a *API) createChapter(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	seriesID := chi.URLParam(r, "seriesID")
	if !uuidPattern.MatchString(seriesID) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	var body model.ChapterCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if body.Status == "" {
		body.Status = "draft"
	}
	if !slugPattern.MatchString(body.Slug) {
		bodyValidation(w, "slug", "Value error, Slug must be lowercase kebab-case.")
		return
	}
	if !validChapterStatus(body.Status) {
		bodyValidation(w, "status", "Input should be 'draft' or 'published'")
		return
	}
	if !validChapterNumber(body.ChapterNumber) {
		bodyValidation(w, "chapter_number", "Chapter number must be finite, greater than 0 and at most 999999.99")
		return
	}
	if body.Status == "published" {
		bodyValidation(w, "status", "Create the chapter as draft, add at least one page, then publish it.")
		return
	}
	x, err := a.store.CreateChapter(r.Context(), seriesID, body)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Series not found.")
		return
	}
	if errors.Is(err, store.ErrConflict) {
		detail(w, http.StatusConflict, "Chapter number or slug already exists.")
		return
	}
	if errors.Is(err, store.ErrNoPages) {
		detail(w, http.StatusUnprocessableEntity, "A chapter must contain at least one page before it can be published.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateChapterCaches(r)
	writeJSON(w, http.StatusCreated, x)
}

func (a *API) updateChapter(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	seriesID := chi.URLParam(r, "seriesID")
	chapterID := chi.URLParam(r, "chapterID")
	if !uuidPattern.MatchString(seriesID) || !uuidPattern.MatchString(chapterID) {
		detail(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	var body model.ChapterUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		bodyValidation(w, "body", "Input should be a valid JSON object")
		return
	}
	if body.Slug != nil && !slugPattern.MatchString(*body.Slug) {
		bodyValidation(w, "slug", "Value error, Slug must be lowercase kebab-case.")
		return
	}
	if body.Status != nil && !validChapterStatus(*body.Status) {
		bodyValidation(w, "status", "Input should be 'draft' or 'published'")
		return
	}
	if body.ChapterNumber != nil && !validChapterNumber(*body.ChapterNumber) {
		bodyValidation(w, "chapter_number", "Chapter number must be finite, greater than 0 and at most 999999.99")
		return
	}
	x, err := a.store.UpdateChapter(r.Context(), seriesID, chapterID, body)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if errors.Is(err, store.ErrConflict) {
		detail(w, http.StatusConflict, "Chapter number or slug already exists.")
		return
	}
	if errors.Is(err, store.ErrNoPages) {
		detail(w, http.StatusUnprocessableEntity, "A chapter must contain at least one page before it can be published.")
		return
	}
	if errors.Is(err, store.ErrPublicationRequiresMedia) {
		detail(w, http.StatusConflict, "Publish chapters through Media so Catalog can verify durable publication evidence.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateChapterCaches(r)
	writeJSON(w, http.StatusOK, x)
}

func (a *API) deleteChapter(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	seriesID := chi.URLParam(r, "seriesID")
	chapterID := chi.URLParam(r, "chapterID")
	if !uuidPattern.MatchString(seriesID) || !uuidPattern.MatchString(chapterID) {
		detail(w, http.StatusNotFound, "Series or chapter not found.")
		return
	}
	cleanupJobID, err := a.store.DeleteChapter(r.Context(), seriesID, chapterID)
	if errors.Is(err, store.ErrNotFound) {
		detail(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.internal(w, err)
		return
	}
	a.invalidateChapterCaches(r)
	writeJSON(w, http.StatusAccepted, map[string]any{
		"catalog_removed": true,
		"storage_cleanup": "queued",
		"job_id":          cleanupJobID,
	})
}

func (a *API) publishChapter(w http.ResponseWriter, r *http.Request) {
	if !a.requireShadowWrite(w, r) {
		return
	}
	publicationDomainError(w, http.StatusConflict, "publication_requires_media", "Chapter publication requires verified Media evidence")
}

func (a *API) invalidateChapterCaches(r *http.Request) {
	if err := a.cache.InvalidateScope(r.Context(), "series"); err != nil {
		a.log.Warn("series cache invalidation failed", "error", err)
	}
	if err := a.cache.InvalidateScope(r.Context(), "chapter"); err != nil {
		a.log.Warn("chapter cache invalidation failed", "error", err)
	}
}

func (a *API) invalidateCurationCaches(r *http.Request) {
	if err := a.cache.InvalidateScope(r.Context(), "curation"); err != nil {
		a.log.Warn("curation cache invalidation failed", "error", err)
	}
}

func validChapterStatus(value string) bool {
	return value == "draft" || value == "published"
}

func validChapterNumber(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value > 0 && value <= 999999.99
}

func (a *API) requireShadowWrite(w http.ResponseWriter, r *http.Request) bool {
	_, statusCode, message := a.sessions.RequireAdmin(r.Context(), r)
	if statusCode != 0 {
		detail(w, statusCode, message)
		return false
	}
	if !a.enableWrites {
		detail(w, http.StatusServiceUnavailable, "Catalog Go shadow writes are disabled")
		return false
	}
	return true
}

func normalizeTagNames(values []string) []string {
	out := make([]string, 0, len(values))
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		tag := strings.ToUpper(strings.TrimSpace(value))
		if tag == "" {
			continue
		}
		if _, exists := seen[tag]; exists {
			continue
		}
		seen[tag] = struct{}{}
		out = append(out, tag)
	}
	return out
}

func validSeriesStatus(value string) bool {
	return value == "ongoing" || value == "completed" || value == "hiatus" || value == "cancelled"
}

func validTagNames(values []string) bool {
	if len(values) > 50 {
		return false
	}
	for _, raw := range values {
		name := strings.TrimSpace(raw)
		if name == "" {
			continue
		}
		if !utf8.ValidString(name) || utf8.RuneCountInString(name) > 100 {
			return false
		}
	}
	return true
}

func bodyValidation(w http.ResponseWriter, field, msg string) {
	writeJSON(w, http.StatusUnprocessableEntity, map[string]any{
		"detail": []map[string]any{{
			"type":  "value_error",
			"loc":   []any{"body", field},
			"msg":   msg,
			"input": nil,
		}},
	})
}

func (a *API) internal(w http.ResponseWriter, err error) {
	a.log.Error("request failed", "error", err)
	detail(w, 500, "Internal Server Error")
}
func parseBounded(raw string, def, min, max int) (int, bool) {
	if raw == "" {
		return def, true
	}
	n, e := strconv.Atoi(raw)
	return n, e == nil && n >= min && n <= max
}
func validation(w http.ResponseWriter, field string) {
	writeJSON(w, 422, map[string]any{"detail": []map[string]any{{"type": "value_error", "loc": []any{"query", field}, "msg": "Input should be a valid value", "input": nil}}})
}
func detail(w http.ResponseWriter, status int, msg string) {
	writeErrorJSON(w, status, "", msg)
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
