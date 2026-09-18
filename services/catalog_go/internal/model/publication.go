package model

// PublicationAsset is immutable Media output evidence carried by the validated
// Catalog publication command. Catalog persists delivery metadata, but Media
// remains the owner of byte/checksum evidence.
type PublicationAsset struct {
	ImagePath string `json:"image_path"`
	Width     int    `json:"width"`
	Height    int    `json:"height"`
	SizeBytes int64  `json:"size_bytes"`
	SHA256    string `json:"sha256"`
}

type PublicationPage struct {
	PublicationAsset
	PageNumber      int               `json:"page_number"`
	EncodingVersion int               `json:"encoding_version"`
	EncodingRows    int               `json:"encoding_rows"`
	EncodingColumns int               `json:"encoding_columns"`
	EncodingSeed    string            `json:"encoding_seed"`
	Responsive      *PublicationAsset `json:"responsive"`
}

type PublicationManifest struct {
	SchemaVersion int               `json:"schema_version"`
	SeriesID      string            `json:"series_id"`
	SeriesSlug    string            `json:"series_slug"`
	ChapterSlug   string            `json:"chapter_slug"`
	Pages         []PublicationPage `json:"pages"`
}

// PublicationCommand mirrors contracts/catalog/v1/publication.schema.json.
// ManifestSHA256 is derived by the authenticated command boundary from the
// validated manifest and is intentionally not accepted as a wire field.
type PublicationCommand struct {
	SchemaVersion       int                 `json:"schema_version"`
	IdempotencyKey      string              `json:"idempotency_key"`
	OperationID         string              `json:"operation_id"`
	ActorID             string              `json:"actor_id"`
	SourceRevision      int64               `json:"source_revision"`
	IngestionGeneration int64               `json:"ingestion_generation"`
	MediaOperationID    string              `json:"media_operation_id"`
	MediaGeneration     int64               `json:"media_generation"`
	ChapterID           *string             `json:"chapter_id"`
	ExpectedRevision    int64               `json:"expected_revision"`
	ChapterNumber       string              `json:"chapter_number"`
	Title               *string             `json:"title"`
	Manifest            PublicationManifest `json:"manifest"`
	PayloadSHA256       string              `json:"payload_sha256"`
	ManifestSHA256      string              `json:"-"`
	RequestID           string              `json:"-"`
}

type MediaCompletionEvidence struct {
	SchemaVersion    int    `json:"schema_version"`
	Status           string `json:"status"`
	MediaOperationID string `json:"media_operation_id"`
	OperationID      string `json:"operation_id"`
	ActorID          string `json:"actor_id"`
	SourceRevision   int64  `json:"source_revision"`
	MediaGeneration  int64  `json:"media_generation"`
	PageCount        int    `json:"page_count"`
	ManifestSHA256   string `json:"manifest_sha256"`
}

type CatalogMutationReceipt struct {
	SchemaVersion      int    `json:"schema_version"`
	Status             string `json:"status"`
	IdempotencyKey     string `json:"idempotency_key"`
	OperationID        string `json:"operation_id"`
	ActorID            string `json:"actor_id"`
	PayloadSHA256      string `json:"payload_sha256"`
	SeriesID           string `json:"series_id"`
	ChapterID          string `json:"chapter_id"`
	ChapterRevision    int64  `json:"chapter_revision"`
	SeriesRevision     int64  `json:"series_revision"`
	PageCount          int    `json:"page_count"`
	PublicationEventID string `json:"publication_event_id"`
}
