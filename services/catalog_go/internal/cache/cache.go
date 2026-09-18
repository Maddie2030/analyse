package cache

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	defaultLocalMaxEntries = 512
	defaultLocalMaxBytes   = 16 * 1024 * 1024
	defaultLocalMaxObject  = 1024 * 1024
	invalidationChannel    = "catalog:invalidate:v1"
)

type localEntry struct {
	scope     string
	body      []byte
	expiresAt time.Time
}

type flight struct {
	done chan struct{}
	body []byte
	err  error
}

type Service struct {
	redis      *redis.Client
	mu         sync.Mutex
	local      map[string]localEntry
	order      []string
	localBytes int
	generation uint64
	scopeGen   map[string]uint64

	flightMu sync.Mutex
	flights  map[string]*flight
}

func New(client *redis.Client) *Service {
	return &Service{
		redis:    client,
		local:    make(map[string]localEntry, defaultLocalMaxEntries),
		order:    make([]string, 0, defaultLocalMaxEntries),
		scopeGen: make(map[string]uint64),
		flights:  make(map[string]*flight),
	}
}

func localKey(scope, key string) string {
	return scope + "\x00" + key
}

func (s *Service) GetLocal(scope, key string) ([]byte, bool) {
	storageKey := localKey(scope, key)
	now := time.Now()
	s.mu.Lock()
	defer s.mu.Unlock()
	entry, ok := s.local[storageKey]
	if !ok {
		return nil, false
	}
	if now.After(entry.expiresAt) {
		s.localBytes -= len(entry.body)
		delete(s.local, storageKey)
		return nil, false
	}
	return append([]byte(nil), entry.body...), true
}

func (s *Service) setLocalLocked(scope, key string, body []byte, ttl time.Duration) {
	storageKey := localKey(scope, key)
	if old, exists := s.local[storageKey]; exists {
		s.localBytes -= len(old.body)
	} else {
		s.order = append(s.order, storageKey)
	}
	s.local[storageKey] = localEntry{scope: scope, body: body, expiresAt: time.Now().Add(ttl)}
	s.localBytes += len(body)

	for (len(s.local) > defaultLocalMaxEntries || s.localBytes > defaultLocalMaxBytes) && len(s.order) > 0 {
		victim := s.order[0]
		s.order = s.order[1:]
		entry, ok := s.local[victim]
		if !ok {
			continue
		}
		if victim == storageKey && len(s.local) == 1 {
			break
		}
		s.localBytes -= len(entry.body)
		delete(s.local, victim)
	}

	if len(s.order) > defaultLocalMaxEntries*2 {
		compact := make([]string, 0, len(s.local))
		seen := make(map[string]struct{}, len(s.local))
		for _, candidate := range s.order {
			if _, exists := s.local[candidate]; !exists {
				continue
			}
			if _, duplicate := seen[candidate]; duplicate {
				continue
			}
			compact = append(compact, candidate)
			seen[candidate] = struct{}{}
		}
		s.order = compact
	}
}

func (s *Service) SetLocal(scope, key string, body []byte, ttl time.Duration) {
	if ttl <= 0 || len(body) == 0 || len(body) > defaultLocalMaxObject {
		return
	}
	copied := append([]byte(nil), body...)
	s.mu.Lock()
	s.setLocalLocked(scope, key, copied, ttl)
	s.mu.Unlock()
}

func (s *Service) localGeneration(scope string) (uint64, uint64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.generation, s.scopeGen[scope]
}

func (s *Service) setLocalIfGeneration(
	scope, key string,
	body []byte,
	ttl time.Duration,
	generation, scopeGeneration uint64,
) bool {
	if ttl <= 0 || len(body) == 0 || len(body) > defaultLocalMaxObject {
		return false
	}
	copied := append([]byte(nil), body...)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.generation != generation || s.scopeGen[scope] != scopeGeneration {
		return false
	}
	s.setLocalLocked(scope, key, copied, ttl)
	return true
}

func (s *Service) ClearLocal() {
	s.mu.Lock()
	s.generation++
	s.local = make(map[string]localEntry, defaultLocalMaxEntries)
	s.order = s.order[:0]
	s.localBytes = 0
	s.mu.Unlock()
}

func (s *Service) invalidateLocalScope(scope string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.scopeGen[scope]++
	for key, entry := range s.local {
		if entry.scope != scope {
			continue
		}
		s.localBytes -= len(entry.body)
		delete(s.local, key)
	}
}

// LoadLocal performs bounded in-process singleflight on cache misses. Only one
// caller executes loader for a given key; concurrent callers wait for that
// result instead of stampeding PostgreSQL when a hot key expires.
func (s *Service) LoadLocal(
	ctx context.Context,
	scope string,
	key string,
	ttl time.Duration,
	loader func() ([]byte, error),
) (body []byte, state string, err error) {
	if body, ok := s.GetLocal(scope, key); ok {
		return body, "HIT", nil
	}

	flightKey := localKey(scope, key)
	s.flightMu.Lock()
	if existing, ok := s.flights[flightKey]; ok {
		s.flightMu.Unlock()
		select {
		case <-ctx.Done():
			return nil, "COALESCED", ctx.Err()
		case <-existing.done:
			if existing.err != nil {
				return nil, "COALESCED", existing.err
			}
			return append([]byte(nil), existing.body...), "COALESCED", nil
		}
	}
	current := &flight{done: make(chan struct{})}
	s.flights[flightKey] = current
	s.flightMu.Unlock()

	// Capture the cache epoch immediately before executing the DB loader. If an
	// admin mutation invalidates local caches while this loader is in flight, the
	// result may satisfy these already-started callers but must never repopulate
	// the post-invalidation cache with pre-write data.
	generation, scopeGeneration := s.localGeneration(scope)
	body, err = loader()
	if err == nil {
		s.setLocalIfGeneration(scope, key, body, ttl, generation, scopeGeneration)
		current.body = append([]byte(nil), body...)
	}
	current.err = err
	close(current.done)

	s.flightMu.Lock()
	delete(s.flights, flightKey)
	s.flightMu.Unlock()
	return body, "MISS", err
}

func (s *Service) publishInvalidation(ctx context.Context, scope string) error {
	return s.redis.Publish(ctx, invalidationChannel, scope).Err()
}

func (s *Service) Delete(ctx context.Context, scope, key string) error {
	s.invalidateLocalScope(scope)
	pubErr := s.publishInvalidation(ctx, scope)
	delErr := s.redis.Del(ctx, "cache:"+scope+":"+key).Err()
	return errors.Join(pubErr, delErr)
}

// InvalidateScope mirrors the existing Python cache:<scope>:* contract, but uses
// SCAN instead of KEYS so a large cache cannot block Valkey. It also broadcasts
// the invalidation so local caches in the other Catalog plane/replicas are
// cleared immediately instead of waiting for TTL expiry.
func (s *Service) InvalidateScope(ctx context.Context, scope string) error {
	s.invalidateLocalScope(scope)
	var resultErr error
	if err := s.publishInvalidation(ctx, scope); err != nil {
		resultErr = errors.Join(resultErr, err)
	}
	pattern := "cache:" + scope + ":*"
	var cursor uint64
	for {
		keys, next, err := s.redis.Scan(ctx, cursor, pattern, 200).Result()
		if err != nil {
			return errors.Join(resultErr, err)
		}
		if len(keys) > 0 {
			if err := s.redis.Del(ctx, keys...).Err(); err != nil {
				return errors.Join(resultErr, err)
			}
		}
		cursor = next
		if cursor == 0 {
			return resultErr
		}
	}
}

// RunInvalidationLoop maintains one lightweight Pub/Sub subscription per
// Catalog process. The retry loop is intentionally self-healing: a temporary
// Valkey interruption should make cache entries age out naturally, not crash
// Catalog or block reads.
func (s *Service) RunInvalidationLoop(ctx context.Context) {
	backoff := 250 * time.Millisecond
	for ctx.Err() == nil {
		pubsub := s.redis.Subscribe(ctx, invalidationChannel)
		if _, err := pubsub.Receive(ctx); err != nil {
			_ = pubsub.Close()
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
				if backoff < 5*time.Second {
					backoff *= 2
				}
				continue
			}
		}
		backoff = 250 * time.Millisecond
		ch := pubsub.Channel()
		connected := true
		for connected {
			select {
			case <-ctx.Done():
				_ = pubsub.Close()
				return
			case message, ok := <-ch:
				if !ok {
					connected = false
					continue
				}
				s.invalidateLocalScope(message.Payload)
			}
		}
		_ = pubsub.Close()
	}
}
