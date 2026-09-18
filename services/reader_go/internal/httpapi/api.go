package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"mreader/reader/internal/analytics"
	"mreader/reader/internal/cloudfrontcookie"
	"mreader/reader/internal/imagetoken"
	"mreader/reader/internal/session"
	"mreader/reader/internal/store"
)

var readerVisitorID = regexp.MustCompile(`^[A-Za-z0-9_-]{16,64}$`)

var publicThumbnail = regexp.MustCompile(
	`^[a-z0-9]+(?:-[a-z0-9]+)*/thumbnail-[a-f0-9]+\.webp$`,
)

type API struct {
	store                         *store.Store
	sessions                      *session.Service
	imageToken                    *imagetoken.Service
	cloudFrontSigner              *cloudfrontcookie.Signer
	trending                      *analytics.Tracker
	log                           *slog.Logger
	seaweedFiler                  string
	allowedOrigins                map[string]struct{}
	debug                         bool
	allowSessionlessImageDelivery bool
	httpClient                    *http.Client
}

type pageResponse struct {
	PageNumber          int     `json:"page_number"`
	ImagePath           string  `json:"image_path"`
	Width               *int    `json:"width"`
	Height              *int    `json:"height"`
	ResponsiveImagePath *string `json:"responsive_image_path,omitempty"`
	ResponsiveWidth     *int    `json:"responsive_width,omitempty"`
	ResponsiveHeight    *int    `json:"responsive_height,omitempty"`
	EncodingVersion     int     `json:"encoding_version"`
	EncodingRows        *int    `json:"encoding_rows"`
	EncodingColumns     *int    `json:"encoding_columns"`
	EncodingSeed        *string `json:"encoding_seed"`
}

type readerResponse struct {
	SeriesID            string             `json:"series_id"`
	SeriesTitle         string             `json:"series_title"`
	SeriesSlug          string             `json:"series_slug"`
	ChapterID           string             `json:"chapter_id"`
	ChapterNumber       float64            `json:"chapter_number"`
	ChapterTitle        *string            `json:"chapter_title"`
	ChapterSlug         string             `json:"chapter_slug"`
	PageCount           int                `json:"page_count"`
	ChapterToken        string             `json:"chapter_token"`
	ChapterEncodingSeed *string            `json:"chapter_encoding_seed,omitempty"`
	Pages               []pageResponse     `json:"pages"`
	PrevChapter         *store.ChapterLink `json:"prev_chapter"`
	NextChapter         *store.ChapterLink `json:"next_chapter"`
}

func New(
	st *store.Store,
	sessions *session.Service,
	imageToken *imagetoken.Service,
	trending *analytics.Tracker,
	log *slog.Logger,
	seaweedFiler string,
	allowedOrigins []string,
	debug bool,
	allowSessionlessImageDelivery bool,
	cloudFrontSigner *cloudfrontcookie.Signer,
) *API {
	allowed := make(map[string]struct{}, len(allowedOrigins))
	for _, origin := range allowedOrigins {
		u, err := url.Parse(origin)
		if err == nil && u.Hostname() != "" {
			allowed[strings.ToLower(u.Hostname())] = struct{}{}
		}
	}

	return &API{
		store:                         st,
		sessions:                      sessions,
		imageToken:                    imageToken,
		cloudFrontSigner:              cloudFrontSigner,
		trending:                      trending,
		log:                           log,
		seaweedFiler:                  strings.TrimRight(seaweedFiler, "/"),
		allowedOrigins:                allowed,
		debug:                         debug,
		allowSessionlessImageDelivery: allowSessionlessImageDelivery,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        64,
				MaxIdleConnsPerHost: 32,
				MaxConnsPerHost:     64,
				IdleConnTimeout:     90 * time.Second,
			},
		},
	}
}

func (a *API) Router() http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(a.requestLogger)
	r.Use(middleware.Recoverer)

	r.Get("/health", a.health)
	r.Get("/api/mobile/v1/health", a.mobileHealth)
	r.Get("/api/mobile/v1/reader/{seriesSlug}/{chapterSlug}/page/{pageNumber}", a.mobilePage)
	r.Get("/api/reader/{seriesSlug}/{chapterSlug}", a.reader)
	r.Get("/api/token/chapter/{seriesSlug}/{chapterSlug}", a.chapterToken)
	r.Post("/api/token/cloudfront/clear", a.clearCloudFrontCookies)
	r.Get("/internal/image-auth", a.imageAuth)
	r.Get("/internal/image-auth/ready", a.imageAuthReady)
	r.Get("/images/*", a.serveImage)

	return r
}

func (a *API) imageAuthReady(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "reader-image-auth",
	})
}

func (a *API) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":            "ok",
		"service":           "reader-go",
		"mode":              "shadow",
		"images_enabled":    true,
		"tokens_enabled":    true,
		"request_logging":   true,
		"trending_tracking": a.trending != nil,
	})
}

// mobileHealth is routed through the public user gateway and lets native
// clients verify that the versioned mobile reader adapter is deployed.
func (a *API) mobileHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "reader-mobile-adapter",
		"version": "v1",
	})
}

func (a *API) reader(w http.ResponseWriter, r *http.Request) {
	seriesSlug := strings.TrimSpace(chi.URLParam(r, "seriesSlug"))
	chapterSlug := strings.TrimSpace(chi.URLParam(r, "chapterSlug"))

	manifest, pages, prev, next, err := a.store.ReaderChapter(
		r.Context(),
		seriesSlug,
		chapterSlug,
	)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("reader query failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	sess := a.sessions.OptionalFromRequest(r.Context(), r)

	var userID *string
	if sess != nil && sess.UserID != "" {
		userID = &sess.UserID
	}

	chapterToken := ""
	if len(pages) > 0 {
		paths := make([]string, 0, len(pages))
		for _, p := range pages {
			paths = append(paths, p.ImagePath)
			if p.ResponsiveImagePath != nil && strings.TrimSpace(*p.ResponsiveImagePath) != "" {
				paths = append(paths, *p.ResponsiveImagePath)
			}
		}
		var err error
		chapterToken, err = a.imageToken.GenerateChapter(r.Context(), manifest.ChapterID, paths, userID)
		if err != nil {
			a.log.Error("chapter image token generation failed", "error", err, "chapter_id", manifest.ChapterID)
			writeError(w, http.StatusInternalServerError, "Internal server error")
			return
		}
	}

	var chapterEncodingSeed *string
	if len(pages) > 0 {
		var candidate string
		homogeneous := true
		for _, p := range pages {
			if p.EncodingVersion == 0 || p.EncodingSeed == nil || strings.TrimSpace(*p.EncodingSeed) == "" {
				homogeneous = false
				break
			}
			if candidate == "" {
				candidate = *p.EncodingSeed
			} else if candidate != *p.EncodingSeed {
				homogeneous = false
				break
			}
		}
		if homogeneous && candidate != "" {
			seed := candidate
			chapterEncodingSeed = &seed
		}
	}

	pageResponses := make([]pageResponse, 0, len(pages))
	for _, p := range pages {
		seed := p.EncodingSeed
		if chapterEncodingSeed != nil && seed != nil && *seed == *chapterEncodingSeed {
			seed = nil
		}
		pageResponses = append(pageResponses, pageResponse{
			PageNumber:          p.PageNumber,
			ImagePath:           p.ImagePath,
			Width:               p.Width,
			Height:              p.Height,
			ResponsiveImagePath: p.ResponsiveImagePath,
			ResponsiveWidth:     p.ResponsiveWidth,
			ResponsiveHeight:    p.ResponsiveHeight,
			EncodingVersion:     p.EncodingVersion,
			EncodingRows:        p.EncodingRows,
			EncodingColumns:     p.EncodingColumns,
			EncodingSeed:        seed,
		})
	}

	if err := a.setCloudFrontChapterCookies(w, manifest.SeriesSlug, manifest.ChapterSlug); err != nil {
		a.log.Error("cloudfront signed cookie generation failed", "error", err, "chapter_id", manifest.ChapterID)
		writeError(w, http.StatusInternalServerError, "Image delivery authorization error")
		return
	}

	if a.trending != nil {
		actorKey := ""
		if sess != nil && sess.UserID != "" {
			actorKey = "user:" + sess.UserID
		} else if visitor := strings.TrimSpace(r.Header.Get("X-MReader-Visitor")); readerVisitorID.MatchString(visitor) {
			actorKey = "visitor:" + visitor
		}
		a.trending.Track(manifest.SeriesID, actorKey)
	}

	writeJSON(w, http.StatusOK, readerResponse{
		SeriesID:            manifest.SeriesID,
		SeriesTitle:         manifest.SeriesTitle,
		SeriesSlug:          manifest.SeriesSlug,
		ChapterID:           manifest.ChapterID,
		ChapterNumber:       manifest.ChapterNumber,
		ChapterTitle:        manifest.ChapterTitle,
		ChapterSlug:         manifest.ChapterSlug,
		PageCount:           manifest.PageCount,
		ChapterToken:        chapterToken,
		ChapterEncodingSeed: chapterEncodingSeed,
		Pages:               pageResponses,
		PrevChapter:         prev,
		NextChapter:         next,
	})
}

func (a *API) chapterToken(w http.ResponseWriter, r *http.Request) {
	seriesSlug := strings.TrimSpace(chi.URLParam(r, "seriesSlug"))
	chapterSlug := strings.TrimSpace(chi.URLParam(r, "chapterSlug"))

	sess := a.sessions.OptionalFromRequest(r.Context(), r)
	var userID *string
	if sess != nil && sess.UserID != "" {
		userID = &sess.UserID
	}

	chapterID, paths, err := a.store.ChapterGrantPaths(r.Context(), seriesSlug, chapterSlug)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Chapter not found.")
		return
	}
	if err != nil {
		a.log.Error("chapter grant lookup failed", "error", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	token, err := a.imageToken.GenerateChapter(r.Context(), chapterID, paths, userID)
	if err != nil {
		a.log.Error("chapter token generation failed", "error", err, "chapter_id", chapterID)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if err := a.setCloudFrontChapterCookies(w, seriesSlug, chapterSlug); err != nil {
		a.log.Error("cloudfront signed cookie generation failed", "error", err, "chapter_id", chapterID)
		writeError(w, http.StatusInternalServerError, "Image delivery authorization error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"token": token, "chapter_id": chapterID})
}

func (a *API) setCloudFrontChapterCookies(w http.ResponseWriter, seriesSlug, chapterSlug string) error {
	if a.cloudFrontSigner == nil {
		return nil
	}
	cookies, err := a.cloudFrontSigner.CookiesForChapter(seriesSlug, chapterSlug, time.Now())
	if err != nil {
		return err
	}
	for _, cookie := range cookies {
		http.SetCookie(w, cookie)
	}
	return nil
}

func (a *API) clearCloudFrontCookies(w http.ResponseWriter, _ *http.Request) {
	if a.cloudFrontSigner != nil {
		for _, cookie := range a.cloudFrontSigner.ClearCookies() {
			http.SetCookie(w, cookie)
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

func chapterFromImagePath(path string) (string, string, bool) {
	parts := strings.Split(strings.Trim(strings.TrimSpace(path), "/"), "/")
	if len(parts) < 3 || parts[0] == "" || parts[1] == "" || strings.Contains(parts[0], "..") || strings.Contains(parts[1], "..") {
		return "", "", false
	}
	return parts[0], parts[1], true
}

func (a *API) validateImageRequest(r *http.Request, imagePath, token string) (int, string) {
	imagePath = strings.TrimSpace(imagePath)
	if imagePath == "" || strings.Contains(imagePath, "..") || strings.HasPrefix(imagePath, "/") {
		return http.StatusBadRequest, "Invalid image path"
	}

	if !a.debug && !a.hotlinkAllowed(r) {
		return http.StatusForbidden, "Hotlinking not allowed"
	}

	if publicThumbnail.MatchString(imagePath) {
		return http.StatusNoContent, ""
	}

	token = strings.TrimSpace(token)
	if token == "" {
		return http.StatusForbidden, "Missing token. Access denied."
	}

	sess := a.sessions.OptionalFromRequest(r.Context(), r)
	var userID *string
	if sess != nil && sess.UserID != "" {
		userID = &sess.UserID
	}

	if !a.imageToken.VerifyDelivery(r.Context(), token, imagePath, userID, a.allowSessionlessImageDelivery) {
		return http.StatusForbidden, "Invalid or expired token."
	}

	return http.StatusNoContent, ""
}

// mobilePage is the native-reader compatibility adapter. It resolves the page
// from the published chapter database row, validates the existing chapter grant
// against that exact storage path, and streams the still-scrambled bytes from
// SeaweedFS. No decoded/clean image is ever produced by this endpoint.
func (a *API) mobilePage(w http.ResponseWriter, r *http.Request) {
	seriesSlug := strings.TrimSpace(chi.URLParam(r, "seriesSlug"))
	chapterSlug := strings.TrimSpace(chi.URLParam(r, "chapterSlug"))
	pageNumber, err := strconv.Atoi(strings.TrimSpace(chi.URLParam(r, "pageNumber")))
	if err != nil || pageNumber < 1 {
		writeError(w, http.StatusUnprocessableEntity, "Invalid page number.")
		return
	}

	page, err := a.store.ReaderPageAsset(r.Context(), seriesSlug, chapterSlug, pageNumber)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "Page not found.")
		return
	}
	if err != nil {
		a.log.Error("mobile page lookup failed", "error", err, "series", seriesSlug, "chapter", chapterSlug, "page", pageNumber)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	variant := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("variant")))
	imagePath := strings.TrimSpace(page.ImagePath)
	selectedVariant := "primary"
	switch variant {
	case "", "primary":
		// Canonical web-reader page.
	case "responsive":
		if page.ResponsiveImagePath == nil || strings.TrimSpace(*page.ResponsiveImagePath) == "" {
			writeError(w, http.StatusNotFound, "Responsive page variant is unavailable.")
			return
		}
		imagePath = strings.TrimSpace(*page.ResponsiveImagePath)
		selectedVariant = "responsive"
	default:
		writeError(w, http.StatusUnprocessableEntity, "Invalid page variant.")
		return
	}

	status, message := a.validateImageRequest(r, imagePath, r.URL.Query().Get("token"))
	if status != http.StatusNoContent {
		writeError(w, status, message)
		return
	}

	w.Header().Set("X-MReader-Mobile-Adapter", "v1")
	w.Header().Set("X-MReader-Mobile-Variant", selectedVariant)
	a.streamSeaweedAsset(w, r, imagePath, true)
}

// imageAuth is intentionally internal to the Docker backend network.  The
// image-edge proxy calls it for every request (including cache hits), while
// the larger scrambled WebP payload is served directly from the edge cache or
// SeaweedFS.  This preserves per-session authorization without pushing image
// bandwidth through Reader Go.
func (a *API) imageAuth(w http.ResponseWriter, r *http.Request) {
	originalURI := strings.TrimSpace(r.Header.Get("X-Original-URI"))
	if originalURI == "" {
		writeError(w, http.StatusBadRequest, "Missing original image URI")
		return
	}

	parsed, err := url.ParseRequestURI(originalURI)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Invalid original image URI")
		return
	}

	imagePath := strings.TrimSpace(strings.TrimPrefix(parsed.Path, "/images/"))
	status, message := a.validateImageRequest(r, imagePath, parsed.Query().Get("token"))
	if status != http.StatusNoContent {
		writeError(w, status, message)
		return
	}

	w.Header().Set("X-MReader-Image-Path", imagePath)
	if publicThumbnail.MatchString(imagePath) {
		w.Header().Set("X-MReader-Public-Image", "1")
	}
	w.WriteHeader(http.StatusNoContent)
}

func (a *API) serveImage(w http.ResponseWriter, r *http.Request) {
	imagePath := strings.TrimSpace(strings.TrimPrefix(r.URL.Path, "/images/"))
	status, message := a.validateImageRequest(r, imagePath, r.URL.Query().Get("token"))
	if status != http.StatusNoContent {
		writeError(w, status, message)
		return
	}
	a.streamSeaweedAsset(w, r, imagePath, false)
}

func (a *API) streamSeaweedAsset(w http.ResponseWriter, r *http.Request, imagePath string, mobileAdapter bool) {
	targetURL := a.seaweedFiler + "/" + strings.TrimLeft(imagePath, "/")
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, targetURL, nil)
	if err != nil {
		writeError(w, http.StatusBadGateway, "Image storage error")
		return
	}

	resp, err := a.httpClient.Do(req)
	if err != nil {
		a.log.Error("seaweedfs image fetch failed", "error", err, "path", imagePath, "mobile_adapter", mobileAdapter)
		writeError(w, http.StatusBadGateway, "Image storage error")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusNotFound {
		writeError(w, http.StatusNotFound, "Image not found")
		return
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		a.log.Error("seaweedfs image fetch returned error", "path", imagePath, "status", resp.StatusCode, "mobile_adapter", mobileAdapter)
		writeError(w, http.StatusBadGateway, "Image storage error")
		return
	}

	contentType := resp.Header.Get("Content-Type")
	if contentType == "" {
		if strings.HasSuffix(strings.ToLower(imagePath), ".mrt") {
			contentType = "application/octet-stream"
		} else {
			contentType = "image/webp"
		}
	}

	w.Header().Set("Content-Type", contentType)
	if publicThumbnail.MatchString(imagePath) {
		w.Header().Set("Cache-Control", "public, max-age=3600, immutable")
	} else if strings.Contains(imagePath, "/_v4/") {
		w.Header().Set("Cache-Control", "private, max-age=300, immutable")
	} else {
		w.Header().Set("Cache-Control", "private, no-store")
	}
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(http.StatusOK)

	if _, err := io.Copy(w, resp.Body); err != nil {
		a.log.Error("image stream failed", "error", err, "path", imagePath, "mobile_adapter", mobileAdapter)
	}
}

func (a *API) hotlinkAllowed(r *http.Request) bool {
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	referer := strings.TrimSpace(r.Header.Get("Referer"))

	var candidate string
	if origin != "" {
		candidate = origin
	} else if referer != "" {
		candidate = referer
	} else {
		// Match Python behavior: absence of Origin/Referer is allowed.
		return true
	}

	u, err := url.Parse(candidate)
	if err != nil || u.Hostname() == "" {
		return true
	}

	_, ok := a.allowedOrigins[strings.ToLower(u.Hostname())]
	return ok
}

func chapterImageScope(seriesSlug, chapterSlug string) string {
	seriesSlug = strings.Trim(strings.TrimSpace(seriesSlug), "/")
	chapterSlug = strings.Trim(strings.TrimSpace(chapterSlug), "/")
	if seriesSlug == "" || chapterSlug == "" || strings.Contains(seriesSlug, "..") || strings.Contains(chapterSlug, "..") {
		return ""
	}
	return seriesSlug + "/" + chapterSlug + "/"
}

func queryInt(r *http.Request, key string, def, min, max int) int {
	raw := r.URL.Query().Get(key)
	if raw == "" {
		return def
	}

	n, err := strconv.Atoi(raw)
	if err != nil || n < min {
		return def
	}
	if n > max {
		return max
	}
	return n
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
			"operation_id", r.Header.Get("X-MReader-Operation-ID"),
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"duration_ms", time.Since(start).Milliseconds(),
			"remote_addr", r.RemoteAddr,
		)
	})
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
