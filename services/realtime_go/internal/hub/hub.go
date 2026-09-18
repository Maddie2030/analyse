package hub

import (
	"encoding/json"
	"log/slog"
	"sync"

	"github.com/gorilla/websocket"
)

type Client struct {
	Conn      *websocket.Conn
	UserID    string
	SessionID string
	Send      chan []byte

	closeOnce sync.Once
	done      chan struct{}

	subscriptionsMu sync.Mutex
	subscriptions   map[string]struct{}
}

type Hub struct {
	log       *slog.Logger
	mu        sync.RWMutex
	clients   map[*Client]struct{}
	byUser    map[string]map[*Client]struct{}
	byComment map[string]map[*Client]struct{}
}

func New(log *slog.Logger) *Hub {
	return &Hub{
		log:       log,
		clients:   make(map[*Client]struct{}),
		byUser:    make(map[string]map[*Client]struct{}),
		byComment: make(map[string]map[*Client]struct{}),
	}
}

func NewClient(conn *websocket.Conn, userID, sessionID string) *Client {
	return &Client{
		Conn:          conn,
		UserID:        userID,
		SessionID:     sessionID,
		Send:          make(chan []byte, 64),
		done:          make(chan struct{}),
		subscriptions: make(map[string]struct{}),
	}
}

// Done closes exactly once when the client has been removed or force-closed.
// Send intentionally remains open: broker/pubsub broadcasters can hold a
// snapshot briefly after unregister, so closing Send would create a
// send-on-closed-channel panic race.
func (c *Client) Done() <-chan struct{} {
	return c.done
}

func (c *Client) Closed() bool {
	select {
	case <-c.done:
		return true
	default:
		return false
	}
}

func (c *Client) Close() {
	c.closeOnce.Do(func() {
		close(c.done)
		if c.Conn != nil {
			_ = c.Conn.Close()
		}
	})
}

func (h *Hub) Register(client *Client) {
	if client == nil || client.Closed() {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if client.Closed() {
		return
	}
	h.clients[client] = struct{}{}
	if client.UserID != "" {
		if h.byUser[client.UserID] == nil {
			h.byUser[client.UserID] = make(map[*Client]struct{})
		}
		h.byUser[client.UserID][client] = struct{}{}
	}
}

func (h *Hub) Unregister(client *Client) {
	if client == nil {
		return
	}

	h.mu.Lock()
	if _, ok := h.clients[client]; ok {
		delete(h.clients, client)
		if client.UserID != "" {
			delete(h.byUser[client.UserID], client)
			if len(h.byUser[client.UserID]) == 0 {
				delete(h.byUser, client.UserID)
			}
		}
		client.subscriptionsMu.Lock()
		for key := range client.subscriptions {
			delete(h.byComment[key], client)
			if len(h.byComment[key]) == 0 {
				delete(h.byComment, key)
			}
		}
		client.subscriptions = make(map[string]struct{})
		client.subscriptionsMu.Unlock()
	}
	h.mu.Unlock()

	// Close outside the hub lock. Broadcast snapshots that were already taken
	// will observe Done and safely skip this client; Send is never closed.
	client.Close()
}

func (h *Hub) SubscribeComment(client *Client, key string) {
	if client == nil || key == "" {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, registered := h.clients[client]; !registered || client.Closed() {
		return
	}
	client.subscriptionsMu.Lock()
	defer client.subscriptionsMu.Unlock()
	if _, exists := client.subscriptions[key]; exists {
		return
	}
	client.subscriptions[key] = struct{}{}
	if h.byComment[key] == nil {
		h.byComment[key] = make(map[*Client]struct{})
	}
	h.byComment[key][client] = struct{}{}
}

func (h *Hub) UnsubscribeComment(client *Client, key string) {
	if client == nil || key == "" {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	client.subscriptionsMu.Lock()
	defer client.subscriptionsMu.Unlock()
	delete(client.subscriptions, key)
	delete(h.byComment[key], client)
	if len(h.byComment[key]) == 0 {
		delete(h.byComment, key)
	}
}

func (h *Hub) BroadcastUser(userID string, value any) {
	body, err := json.Marshal(value)
	if err != nil {
		h.log.Error("marshal realtime user event failed", "error", err)
		return
	}
	h.mu.RLock()
	clients := snapshot(h.byUser[userID])
	h.mu.RUnlock()
	for _, client := range clients {
		if !enqueue(client, body) {
			h.Unregister(client)
		}
	}
}

func (h *Hub) BroadcastComment(key string, value any) {
	body, err := json.Marshal(value)
	if err != nil {
		h.log.Error("marshal realtime comment event failed", "error", err)
		return
	}
	h.mu.RLock()
	clients := snapshot(h.byComment[key])
	h.mu.RUnlock()
	for _, client := range clients {
		if !enqueue(client, body) {
			h.Unregister(client)
		}
	}
}

func (h *Hub) Counts() (clients int, authenticatedUsers int, commentSubscriptions int) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients), len(h.byUser), len(h.byComment)
}

func snapshot(values map[*Client]struct{}) []*Client {
	if len(values) == 0 {
		return nil
	}
	result := make([]*Client, 0, len(values))
	for client := range values {
		result = append(result, client)
	}
	return result
}

func enqueue(client *Client, body []byte) bool {
	if client == nil {
		return false
	}
	select {
	case <-client.Done():
		return false
	default:
	}

	select {
	case <-client.Done():
		return false
	case client.Send <- body:
		return true
	default:
		// A slow browser must not block broker/pubsub consumers. Force-closing
		// the connection and returning false lets the hub remove it immediately;
		// canonical API refresh recovers any live signal missed while disconnected.
		client.Close()
		return false
	}
}
