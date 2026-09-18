package imagetoken

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	defaultGrantCacheTTL = 5 * time.Second
	defaultGrantCacheMax = 1024
)

type cachedGrant struct {
	value     storedValue
	pathSet   map[string]struct{}
	expiresAt time.Time
}

type Service struct {
	redis      *redis.Client
	secret     []byte
	ttl        time.Duration
	cacheTTL   time.Duration
	cacheMax   int
	cacheMu    sync.Mutex
	grantCache map[string]cachedGrant
	cacheOrder []string
}

type payload struct {
	ChapterID string  `json:"chapter_id"`
	Exp       int64   `json:"exp"`
	UID       *string `json:"uid"`
	JTI       string  `json:"jti"`
}

type storedValue struct {
	ChapterID string   `json:"chapter_id"`
	Paths     []string `json:"paths"`
	ExpiresAt int64    `json:"expires_at"`
	UserID    *string  `json:"user_id"`
}

func New(client *redis.Client, secret string, ttlSeconds int) *Service {
	return &Service{
		redis: client, secret: []byte(secret), ttl: time.Duration(ttlSeconds) * time.Second,
		cacheTTL: defaultGrantCacheTTL, cacheMax: defaultGrantCacheMax,
		grantCache: make(map[string]cachedGrant, defaultGrantCacheMax),
		cacheOrder: make([]string, 0, defaultGrantCacheMax),
	}
}

func randomJTI() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}

func cleanPath(value string) (string, error) {
	value = strings.TrimSpace(strings.TrimLeft(value, "/"))
	if value == "" || strings.Contains(value, "..") {
		return "", errors.New("invalid image path")
	}
	return value, nil
}

func normalizePaths(values []string) ([]string, error) {
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		v, err := cleanPath(value)
		if err != nil {
			return nil, err
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	if len(out) == 0 {
		return nil, errors.New("chapter grant needs at least one path")
	}
	sort.Strings(out)
	return out, nil
}

func (s *Service) buildToken(chapterID string, paths []string, userID *string) (string, string, error) {
	expiresAt := time.Now().Unix() + int64(s.ttl/time.Second)
	jti, err := randomJTI()
	if err != nil {
		return "", "", err
	}
	p := payload{ChapterID: chapterID, Exp: expiresAt, UID: userID, JTI: jti}
	rawPayload, err := json.Marshal(p)
	if err != nil {
		return "", "", err
	}
	payloadB64 := base64.RawURLEncoding.EncodeToString(rawPayload)
	mac := hmac.New(sha256.New, s.secret)
	_, _ = mac.Write([]byte(payloadB64))
	token := payloadB64 + "." + hex.EncodeToString(mac.Sum(nil))
	storeRaw, err := json.Marshal(storedValue{ChapterID: chapterID, Paths: paths, ExpiresAt: expiresAt, UserID: userID})
	if err != nil {
		return "", "", err
	}
	return token, string(storeRaw), nil
}

func tokenKey(token string) string {
	h := sha256.Sum256([]byte(token))
	return "imgtoken:" + hex.EncodeToString(h[:])
}

// GenerateChapter creates the only supported image grant: one signed/Redis
// chapter grant whose allow-list is the exact set of objects belonging to the
// chapter. No path, prefix-scope, or per-page grants are accepted.
func (s *Service) GenerateChapter(ctx context.Context, chapterID string, paths []string, userID *string) (string, error) {
	chapterID = strings.TrimSpace(chapterID)
	if chapterID == "" {
		return "", errors.New("chapter id required")
	}
	cleaned, err := normalizePaths(paths)
	if err != nil {
		return "", err
	}
	token, raw, err := s.buildToken(chapterID, cleaned, userID)
	if err != nil {
		return "", err
	}
	if err := s.redis.SetEx(ctx, tokenKey(token), raw, s.ttl).Err(); err != nil {
		return "", err
	}
	return token, nil
}

func cachedPathAllowed(grant cachedGrant, imagePath string) bool {
	_, ok := grant.pathSet[imagePath]
	return ok
}

func (s *Service) cacheGet(key string) (cachedGrant, bool) {
	now := time.Now()
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	grant, ok := s.grantCache[key]
	if !ok {
		return cachedGrant{}, false
	}
	if now.After(grant.expiresAt) || grant.value.ExpiresAt < now.Unix() {
		delete(s.grantCache, key)
		return cachedGrant{}, false
	}
	return grant, true
}

func (s *Service) cachePut(key string, value storedValue) cachedGrant {
	now := time.Now()
	expiresAt := now.Add(s.cacheTTL)
	if tokenExpiry := time.Unix(value.ExpiresAt, 0); tokenExpiry.Before(expiresAt) {
		expiresAt = tokenExpiry
	}
	grant := cachedGrant{value: value, expiresAt: expiresAt, pathSet: make(map[string]struct{}, len(value.Paths))}
	for _, path := range value.Paths {
		grant.pathSet[path] = struct{}{}
	}
	grant.value.Paths = nil

	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	if _, exists := s.grantCache[key]; !exists {
		s.cacheOrder = append(s.cacheOrder, key)
	}
	s.grantCache[key] = grant
	for len(s.grantCache) > s.cacheMax && len(s.cacheOrder) > 0 {
		victim := s.cacheOrder[0]
		s.cacheOrder = s.cacheOrder[1:]
		if victim == key {
			continue
		}
		delete(s.grantCache, victim)
	}
	if len(s.cacheOrder) > s.cacheMax*2 {
		order := make([]string, 0, len(s.grantCache))
		for _, candidate := range s.cacheOrder {
			if _, ok := s.grantCache[candidate]; ok {
				order = append(order, candidate)
			}
		}
		s.cacheOrder = order
	}
	return grant
}

func (s *Service) cacheDelete(key string) {
	s.cacheMu.Lock()
	delete(s.grantCache, key)
	s.cacheMu.Unlock()
}

func (s *Service) decodeAndVerifySignature(token string) (*payload, bool) {
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return nil, false
	}
	payloadB64, provided := parts[0], parts[1]
	mac := hmac.New(sha256.New, s.secret)
	_, _ = mac.Write([]byte(payloadB64))
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(provided)) {
		return nil, false
	}
	raw, err := base64.RawURLEncoding.DecodeString(payloadB64)
	if err != nil {
		return nil, false
	}
	var p payload
	if json.Unmarshal(raw, &p) != nil || strings.TrimSpace(p.ChapterID) == "" {
		return nil, false
	}
	return &p, true
}

func sameUser(expected, actual *string, allowMissing bool) bool {
	if expected == nil || *expected == "" {
		return actual == nil || *actual == ""
	}
	if actual == nil || *actual == "" {
		return allowMissing
	}
	return *expected == *actual
}

// VerifyDelivery requires a valid chapter grant and exact allow-list match.
// A dedicated CDN hostname may omit the browser session; if a session is
// present it must still match the grant owner.
func (s *Service) VerifyDelivery(ctx context.Context, token, imagePath string, userID *string, allowMissingUser bool) bool {
	imagePath, err := cleanPath(imagePath)
	if err != nil {
		return false
	}
	p, ok := s.decodeAndVerifySignature(token)
	if !ok || time.Now().Unix() > p.Exp || !sameUser(p.UID, userID, allowMissingUser) {
		return false
	}
	key := tokenKey(token)
	if grant, hit := s.cacheGet(key); hit {
		return grant.value.ChapterID == p.ChapterID && cachedPathAllowed(grant, imagePath) && sameUser(grant.value.UserID, userID, allowMissingUser)
	}
	raw, err := s.redis.Get(ctx, key).Result()
	if err != nil {
		return false
	}
	var stored storedValue
	if json.Unmarshal([]byte(raw), &stored) != nil || stored.ExpiresAt < time.Now().Unix() || stored.ChapterID != p.ChapterID || len(stored.Paths) == 0 {
		return false
	}
	grant := s.cachePut(key, stored)
	return cachedPathAllowed(grant, imagePath) && sameUser(stored.UserID, userID, allowMissingUser)
}

func (s *Service) Verify(ctx context.Context, token, imagePath string, userID *string) bool {
	return s.VerifyDelivery(ctx, token, imagePath, userID, false)
}

func (s *Service) Revoke(ctx context.Context, token string) error {
	key := tokenKey(token)
	s.cacheDelete(key)
	return s.redis.Del(ctx, key).Err()
}
