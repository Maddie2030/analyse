package store

import (
	"strings"
	"testing"
)

func TestEnqueueRealtimeBatchSQLUsesUnambiguousParameterTypes(t *testing.T) {
	for _, want := range []string{
		"$1::text",
		"$2::text",
		"$3::jsonb",
		"NULL::uuid",
		"$4::uuid",
	} {
		if !strings.Contains(enqueueRealtimeBatchSQL, want) {
			t.Fatalf("enqueue realtime SQL missing %q", want)
		}
	}
	if strings.Contains(enqueueRealtimeBatchSQL, "$1::uuid") {
		t.Fatal("source event parameter must not be inferred as both text and uuid")
	}
}
