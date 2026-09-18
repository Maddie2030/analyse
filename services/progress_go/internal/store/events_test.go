package store

import (
	"encoding/json"
	"testing"
	"time"
)

func TestProgressUpdatedEventSourceMatchesPersistencePath(t *testing.T) {
	when := time.Date(2026, time.September, 12, 10, 30, 0, 0, time.UTC)
	tests := []struct {
		name            string
		sourceMessageID string
		wantSource      string
		wantMessageID   bool
	}{
		{name: "synchronous API transaction", wantSource: "progress-api"},
		{
			name:            "legacy stream drain",
			sourceMessageID: "1720000000000-1",
			wantSource:      "redis-stream-flusher",
			wantMessageID:   true,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			args, err := progressUpdatedEventArgs(
				"11111111-1111-1111-1111-111111111111",
				"22222222-2222-2222-2222-222222222222",
				"33333333-3333-3333-3333-333333333333",
				2,
				0.375,
				when,
				7,
				test.sourceMessageID,
			)
			if err != nil {
				t.Fatalf("progressUpdatedEventArgs returned error: %v", err)
			}

			headersBytes, ok := args[8].([]byte)
			if !ok {
				t.Fatalf("headers type = %T, want []byte", args[8])
			}
			var headers map[string]any
			if err := json.Unmarshal(headersBytes, &headers); err != nil {
				t.Fatalf("decode headers: %v", err)
			}
			if got := headers["source"]; got != test.wantSource {
				t.Fatalf("source = %v, want %q", got, test.wantSource)
			}
			if got := headers["payload_schema"]; got != "v2/progress.updated.schema.json" {
				t.Fatalf("payload_schema = %v", got)
			}
			payloadBytes, ok := args[7].([]byte)
			if !ok {
				t.Fatalf("payload type = %T, want []byte", args[7])
			}
			var payload map[string]any
			if err := json.Unmarshal(payloadBytes, &payload); err != nil {
				t.Fatalf("decode payload: %v", err)
			}
			if got := payload["revision"]; got != float64(7) {
				t.Fatalf("revision = %v, want 7", got)
			}
			_, hasMessageID := headers["source_message_id"]
			if hasMessageID != test.wantMessageID {
				t.Fatalf("source_message_id present = %v, want %v", hasMessageID, test.wantMessageID)
			}
		})
	}
}
