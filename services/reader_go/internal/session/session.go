package session

import (
	"context"
	"encoding/json"
	"net/http"
	"regexp"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	defaultSessionCacheTTL = 5 * time.Second
	defaultSessionCacheMax = 4096
)

type cacheEntry struct {
	session   Session
	expiresAt time.Time
}

type Service struct {
	redis      *redis.Client
	cookieName string
	cacheMu    sync.Mutex
	cache      map[string]cacheEntry
	cacheOrder []string
}

type Session struct {
	Version   int    `json:"version"`
	UserID    string `json:"user_id"`
	Username  string `json:"username"`
	Role      string `json:"role"`
	IsActive  bool   `json:"is_active"`
	CreatedAt string `json:"created_at"`
}

var sessionUUID = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$`)

func validV1SessionFields(s Session) bool {
	if !sessionUUID.MatchString(s.UserID) {
		return false
	}
	if s.CreatedAt == "" {
		return false
	}
	_, err := time.Parse(time.RFC3339Nano, s.CreatedAt)
	return err == nil
}

func (s Session) Valid() bool {
	// Session contract v1 is mandatory in the consolidated baseline.
	if s.Version != 1 {
		return false
	}
	if s.UserID == "" || s.Username == "" || len(s.Username) > 100 || !s.IsActive {
		return false
	}
	if s.Role != "user" && s.Role != "admin" {
		return false
	}
	if !validV1SessionFields(s) {
		return false
	}
	return true
}

func New(client *redis.Client, cookieName string) *Service {
	if cookieName == "" {
		cookieName = "session_id"
	}
	return &Service{
		redis: client, cookieName: cookieName,
		cache:      make(map[string]cacheEntry, defaultSessionCacheMax),
		cacheOrder: make([]string, 0, defaultSessionCacheMax),
	}
}

func (s *Service) cached(sessionID string) (*Session, bool) {
	now := time.Now()
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	entry, ok := s.cache[sessionID]
	if !ok {
		return nil, false
	}
	if now.After(entry.expiresAt) {
		delete(s.cache, sessionID)
		return nil, false
	}
	value := entry.session
	return &value, true
}

func (s *Service) remember(sessionID string, value Session) *Session {
	entry := cacheEntry{session: value, expiresAt: time.Now().Add(defaultSessionCacheTTL)}
	s.cacheMu.Lock()
	if _, exists := s.cache[sessionID]; !exists {
		s.cacheOrder = append(s.cacheOrder, sessionID)
	}
	s.cache[sessionID] = entry
	for len(s.cache) > defaultSessionCacheMax && len(s.cacheOrder) > 0 {
		victim := s.cacheOrder[0]
		s.cacheOrder = s.cacheOrder[1:]
		if victim != sessionID {
			delete(s.cache, victim)
		}
	}
	if len(s.cacheOrder) > defaultSessionCacheMax*2 {
		order := make([]string, 0, len(s.cache))
		for _, candidate := range s.cacheOrder {
			if _, ok := s.cache[candidate]; ok {
				order = append(order, candidate)
			}
		}
		s.cacheOrder = order
	}
	s.cacheMu.Unlock()
	out := value
	return &out
}

func (s *Service) OptionalFromRequest(ctx context.Context, r *http.Request) *Session {
	cookie, err := r.Cookie(s.cookieName)
	if err != nil || cookie.Value == "" {
		return nil
	}
	if value, ok := s.cached(cookie.Value); ok {
		return value
	}

	raw, err := s.redis.Get(ctx, "session:"+cookie.Value).Result()
	if err != nil {
		return nil
	}

	var sess Session
	if err := json.Unmarshal([]byte(raw), &sess); err != nil || !sess.Valid() {
		return nil
	}
	return s.remember(cookie.Value, sess)
}

func (s *Service) RequireUser(ctx context.Context, r *http.Request) (*Session, int, string) {
	sess := s.OptionalFromRequest(ctx, r)
	if sess == nil {
		return nil, http.StatusUnauthorized, "Not authenticated"
	}
	if sess.UserID == "" {
		return nil, http.StatusBadRequest, "Invalid user identifier."
	}
	return sess, 0, ""
}
