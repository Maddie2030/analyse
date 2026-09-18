package httpapi

import (
	"net/http"
	"sync"
)

type canaryMetrics struct {
	mu     sync.RWMutex
	total  uint64
	byPath map[string]uint64
}

func newCanaryMetrics() *canaryMetrics {
	return &canaryMetrics{byPath: make(map[string]uint64)}
}

func (m *canaryMetrics) record(path string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.total++
	m.byPath[path]++
}

func (m *canaryMetrics) snapshot() map[string]any {
	m.mu.RLock()
	defer m.mu.RUnlock()
	paths := make(map[string]uint64, len(m.byPath))
	for k, v := range m.byPath {
		paths[k] = v
	}
	return map[string]any{
		"canary_requests_total": m.total,
		"by_path":               paths,
	}
}

func (a *API) canaryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-MReader-Catalog-Route") == "canary" {
			a.canary.record(r.URL.Path)
			a.log.Info("catalog canary request", "method", r.Method, "path", r.URL.Path, "request_id", r.Header.Get("X-Request-Id"))
		}
		next.ServeHTTP(w, r)
	})
}

func (a *API) canaryStats(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, a.canary.snapshot())
}
