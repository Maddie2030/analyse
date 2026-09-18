package session

import (
	"context"
	"encoding/json"
	"net/http"
	"regexp"
	"time"

	"github.com/redis/go-redis/v9"
)

type Service struct {
	redis      *redis.Client
	cookieName string
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
	return &Service{redis: client, cookieName: cookieName}
}

func (s *Service) OptionalFromRequest(ctx context.Context, r *http.Request) *Session {
	cookie, err := r.Cookie(s.cookieName)
	if err != nil || cookie.Value == "" {
		return nil
	}
	raw, err := s.redis.Get(ctx, "session:"+cookie.Value).Result()
	if err != nil {
		return nil
	}
	var sess Session
	if json.Unmarshal([]byte(raw), &sess) != nil || !sess.Valid() {
		return nil
	}
	return &sess
}

func (s *Service) RequireAdmin(ctx context.Context, r *http.Request) (*Session, int, string) {
	sess := s.OptionalFromRequest(ctx, r)
	if sess == nil {
		return nil, http.StatusUnauthorized, "Not authenticated"
	}
	if sess.Role != "admin" {
		return nil, http.StatusForbidden, "Admin access required"
	}
	return sess, 0, ""
}
