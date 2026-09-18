package hub

import (
	"io"
	"log/slog"
	"sync"
	"testing"
)

func testHub() *Hub {
	return New(slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func TestEnqueueAfterCloseIsSafe(t *testing.T) {
	client := NewClient(nil, "user-1", "session-1")
	client.Close()

	// Regression: RC6 closed Send during unregister. A broadcaster holding a
	// pre-unregister snapshot could then panic here with send on closed channel.
	enqueue(client, []byte(`{"type":"notification.created"}`))

	select {
	case <-client.Done():
	default:
		t.Fatal("closed client did not signal Done")
	}
}

func TestConcurrentBroadcastAndUnregisterDoesNotPanic(t *testing.T) {
	h := testHub()
	const iterations = 1000

	for i := 0; i < iterations; i++ {
		client := NewClient(nil, "user-1", "session-1")
		h.Register(client)

		var wg sync.WaitGroup
		wg.Add(2)
		go func() {
			defer wg.Done()
			h.BroadcastUser("user-1", map[string]any{"type": "notification.created"})
		}()
		go func() {
			defer wg.Done()
			h.Unregister(client)
		}()
		wg.Wait()
	}

	clients, users, subscriptions := h.Counts()
	if clients != 0 || users != 0 || subscriptions != 0 {
		t.Fatalf("hub leaked state: clients=%d users=%d subscriptions=%d", clients, users, subscriptions)
	}
}

func TestSubscribeAfterUnregisterIsIgnored(t *testing.T) {
	h := testHub()
	client := NewClient(nil, "user-1", "session-1")
	h.Register(client)
	h.Unregister(client)
	h.SubscribeComment(client, "series-1:chapter-1")

	clients, users, subscriptions := h.Counts()
	if clients != 0 || users != 0 || subscriptions != 0 {
		t.Fatalf("unregistered client was reintroduced: clients=%d users=%d subscriptions=%d", clients, users, subscriptions)
	}
}

func TestSlowClientIsEvictedWithoutBlockingFanout(t *testing.T) {
	h := testHub()
	client := NewClient(nil, "user-1", "session-1")
	h.Register(client)
	for i := 0; i < cap(client.Send); i++ {
		client.Send <- []byte(`{"type":"queued"}`)
	}

	h.BroadcastUser("user-1", map[string]any{"type": "notification.created"})

	select {
	case <-client.Done():
	default:
		t.Fatal("slow client was not closed")
	}
	clients, users, subscriptions := h.Counts()
	if clients != 0 || users != 0 || subscriptions != 0 {
		t.Fatalf("slow client was not evicted: clients=%d users=%d subscriptions=%d", clients, users, subscriptions)
	}
}
