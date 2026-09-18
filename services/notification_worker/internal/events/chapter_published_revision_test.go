package events

import (
	"encoding/json"
	"testing"
)

const chapterID = "11111111-1111-4111-8111-111111111111"
const seriesID = "22222222-2222-4222-8222-222222222222"

func TestDecodeChapterPublishedVersionedRevision(t *testing.T) {
	v1 := json.RawMessage(`{"chapter_id":"` + chapterID + `","series_id":"` + seriesID + `","chapter_number":1,"chapter_slug":"chapter-1","series_slug":"series","page_count":1,"published_at":"2026-09-15T00:00:00Z"}`)
	gotV1, err := DecodeChapterPublished(v1, 1)
	if err != nil {
		t.Fatalf("decode v1: %v", err)
	}
	if gotV1.ChapterRevision != 0 {
		t.Fatalf("legacy v1 revision = %d, want 0", gotV1.ChapterRevision)
	}

	v2 := json.RawMessage(`{"chapter_id":"` + chapterID + `","series_id":"` + seriesID + `","chapter_revision":2,"chapter_number":1,"chapter_slug":"chapter-1","series_slug":"series","page_count":1,"published_at":"2026-09-15T00:00:00Z"}`)
	gotV2, err := DecodeChapterPublished(v2, 2)
	if err != nil {
		t.Fatalf("decode v2: %v", err)
	}
	if gotV2.ChapterRevision != 2 {
		t.Fatalf("v2 revision = %d, want 2", gotV2.ChapterRevision)
	}

	missingRevision := json.RawMessage(`{"chapter_id":"` + chapterID + `","series_id":"` + seriesID + `","chapter_number":1,"chapter_slug":"chapter-1","series_slug":"series","page_count":1,"published_at":"2026-09-15T00:00:00Z"}`)
	if _, err := DecodeChapterPublished(missingRevision, 2); err == nil {
		t.Fatal("v2 without chapter_revision unexpectedly accepted")
	}
	if _, err := DecodeChapterPublished(v2, 3); err == nil {
		t.Fatal("unknown chapter.published version unexpectedly accepted")
	}
}

func TestChapterPublishedDedupeKeyUsesRevisionForV2(t *testing.T) {
	payload := ChapterPublished{ChapterID: chapterID, ChapterRevision: 7}
	key, err := ChapterPublishedDedupeKey(1, payload)
	if err != nil {
		t.Fatalf("v1 dedupe: %v", err)
	}
	if key != "chapter.published:"+chapterID {
		t.Fatalf("v1 key = %q", key)
	}

	key, err = ChapterPublishedDedupeKey(2, payload)
	if err != nil {
		t.Fatalf("v2 dedupe: %v", err)
	}
	if key != "chapter.published:"+chapterID+":revision:7" {
		t.Fatalf("v2 key = %q", key)
	}
}
