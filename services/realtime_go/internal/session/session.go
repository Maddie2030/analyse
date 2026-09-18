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
	SessionID string `json:"-"`
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
	var value Session
	if err := json.Unmarshal([]byte(raw), &value); err != nil || !value.Valid() {
		return nil
	}
	value.SessionID = cookie.Value
	return &value
}

// Validate checks whether an already-authenticated WebSocket still maps to
// the same active Redis session. redis.Nil means the session was revoked or
// expired; other Redis errors are returned so callers can preserve the socket
// through a transient cache outage instead of logging everyone out.
func (s *Service) Validate(ctx context.Context, sessionID, userID string) (bool, error) {
	if sessionID == "" || userID == "" {
		return false, nil
	}
	raw, err := s.redis.Get(ctx, "session:"+sessionID).Result()
	if err == redis.Nil {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	var value Session
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return false, nil
	}
	return value.Valid() && value.UserID == userID, nil
}
