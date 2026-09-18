package cache

import (
	"testing"
	"time"
)

func TestInvalidateLocalScopeKeepsUnrelatedEntries(t *testing.T) {
	svc := New(nil)
	svc.SetLocal("series", "detail:a", []byte(`{"series":1}`), time.Minute)
	svc.SetLocal("genres", "all", []byte(`["Action"]`), time.Minute)

	svc.invalidateLocalScope("series")

	if _, ok := svc.GetLocal("series", "detail:a"); ok {
		t.Fatal("series entry survived series-scope invalidation")
	}
	if body, ok := svc.GetLocal("genres", "all"); !ok || string(body) != `["Action"]` {
		t.Fatal("unrelated genres entry was evicted")
	}
}

func TestScopedGenerationRejectsOnlyStaleScopeLoader(t *testing.T) {
	svc := New(nil)
	globalGeneration, seriesGeneration := svc.localGeneration("series")
	_, genresGeneration := svc.localGeneration("genres")

	svc.invalidateLocalScope("series")

	if svc.setLocalIfGeneration("series", "detail:a", []byte("stale"), time.Minute, globalGeneration, seriesGeneration) {
		t.Fatal("stale series loader repopulated an invalidated scope")
	}
	if !svc.setLocalIfGeneration("genres", "all", []byte("fresh"), time.Minute, globalGeneration, genresGeneration) {
		t.Fatal("series invalidation incorrectly blocked an unrelated scope")
	}
}
