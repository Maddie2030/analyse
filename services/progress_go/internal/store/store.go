package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type Store struct {
	db *pgxpool.Pool
}

type Target struct {
	SeriesID  string
	ChapterID string
	PageCount int
}

type Progress struct {
	SeriesID          string    `json:"series_id"`
	ChapterID         string    `json:"chapter_id"`
	LastPage          int       `json:"last_page"`
	ScrollPosition    float64   `json:"scroll_position"`
	UpdatedAt         time.Time `json:"updated_at"`
	Revision          int64     `json:"revision"`
	LastOpenedAt      time.Time `json:"last_opened_at"`
	SessionGeneration int64     `json:"session_generation"`
	CommandSequence   int64     `json:"command_sequence"`
}

type HistoryItem struct {
	SeriesID      string    `json:"series_id"`
	SeriesTitle   string    `json:"series_title"`
	SeriesSlug    string    `json:"series_slug"`
	ChapterID     string    `json:"chapter_id"`
	ChapterNumber float64   `json:"chapter_number"`
	ChapterTitle  *string   `json:"chapter_title"`
	ChapterSlug   string    `json:"chapter_slug"`
	ReadAt        time.Time `json:"read_at"`
}

func (s *Store) History(ctx context.Context, userID string, offset, limit int) ([]HistoryItem, error) {
	rows, err := s.db.Query(ctx, `
        SELECT h.series_id::text, s.title, s.slug, h.last_opened_chapter_id::text,
               c.chapter_number::float8, c.title, c.slug, h.last_opened_at
        FROM reading_state_v1 h
        JOIN series s ON s.id=h.series_id
        JOIN chapters c ON c.id=h.last_opened_chapter_id AND c.status='published'
        WHERE h.user_id=$1::uuid AND h.has_history
        ORDER BY h.last_opened_at DESC, h.series_id
        LIMIT $2 OFFSET $3`, userID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]HistoryItem, 0, limit)
	for rows.Next() {
		var item HistoryItem
		if err := rows.Scan(&item.SeriesID, &item.SeriesTitle, &item.SeriesSlug, &item.ChapterID, &item.ChapterNumber, &item.ChapterTitle, &item.ChapterSlug, &item.ReadAt); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

type SeriesState struct {
	SeriesID              string     `json:"series_id"`
	ResumeChapterID       *string    `json:"resume_chapter_id"`
	ResumeChapterSlug     *string    `json:"resume_chapter_slug"`
	ResumeChapterNumber   *float64   `json:"resume_chapter_number"`
	FurthestChapterID     *string    `json:"furthest_chapter_id"`
	FurthestChapterNumber *float64   `json:"furthest_chapter_number"`
	LastPage              *int       `json:"last_page"`
	ScrollPosition        *float64   `json:"scroll_position"`
	UpdatedAt             *time.Time `json:"updated_at"`
	Revision              int64      `json:"revision"`
	LastOpenedAt          *time.Time `json:"last_opened_at"`
	SessionGeneration     int64      `json:"session_generation"`
	ReadChapterIDs        []string   `json:"read_chapter_ids"`
	CompletedChapterIDs   []string   `json:"completed_chapter_ids"`
}

func New(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

// Fail readiness if the command schema/projection migration is absent.
func (s *Store) ValidateReadingSchema(ctx context.Context) error {
	_, err := s.db.Exec(ctx, `SELECT rs.revision, rs.session_generation, rs.last_opened_at,
        cr.command_sequence, cr.command_hash, cr.open_command_id, cr.resume_page
        FROM reading_state_v1 rs JOIN chapter_reads cr ON cr.user_id=rs.user_id AND cr.series_id=rs.series_id
        WHERE FALSE`)
	return err
}

func (s *Store) ResolveTarget(
	ctx context.Context,
	seriesSlug string,
	chapterSlug string,
) (Target, error) {
	var target Target

	err := s.db.QueryRow(
		ctx,
		`SELECT s.id::text, c.id::text, COALESCE(c.page_count, 0)
		   FROM series s
		   JOIN chapters c ON c.series_id = s.id
		  WHERE s.slug = $1
		    AND c.slug = $2
		    AND c.status = 'published'
		  LIMIT 1`,
		seriesSlug,
		chapterSlug,
	).Scan(
		&target.SeriesID,
		&target.ChapterID,
		&target.PageCount,
	)

	if errors.Is(err, pgx.ErrNoRows) {
		return Target{}, ErrNotFound
	}
	return target, err
}

func (s *Store) Get(
	ctx context.Context,
	userID string,
	seriesID string,
) (*Progress, error) {
	return scanProgress(s.db.QueryRow(ctx, currentProgressSQL, userID, seriesID))
}

func (s *Store) GetSeriesState(ctx context.Context, userID, seriesSlug string) (*SeriesState, error) {
	var state SeriesState
	var readIDs, completedIDs []string
	err := s.db.QueryRow(ctx, `
        SELECT
            s.id::text,
            rs.resume_chapter_id::text,
            resume.slug,
            resume.chapter_number::float8,
            rs.furthest_chapter_id::text,
            rs.furthest_chapter_number,
            rs.last_page,
            rs.scroll_position,
	            rs.updated_at,
	            COALESCE(rs.revision, 0),
            rs.last_opened_at,
            COALESCE(rs.session_generation, 0),
            COALESCE((
                SELECT array_agg(cr.chapter_id::text ORDER BY c.chapter_number)
                FROM chapter_reads cr
                JOIN chapters c ON c.id=cr.chapter_id
                WHERE cr.user_id=$1::uuid AND cr.series_id=s.id AND cr.provenance <> 'migrated_reach'
            ), ARRAY[]::text[]),
            COALESCE((
                SELECT array_agg(cr.chapter_id::text ORDER BY c.chapter_number)
                FROM chapter_reads cr
                JOIN chapters c ON c.id=cr.chapter_id
                WHERE cr.user_id=$1::uuid AND cr.series_id=s.id AND cr.completed AND cr.provenance <> 'migrated_reach'
            ), ARRAY[]::text[])
        FROM series s
        LEFT JOIN reading_state_v1 rs ON rs.series_id=s.id AND rs.user_id=$1::uuid
        LEFT JOIN chapters resume ON resume.id=rs.resume_chapter_id AND resume.status='published'
        WHERE s.slug=$2
        LIMIT 1`, userID, seriesSlug,
	).Scan(
		&state.SeriesID,
		&state.ResumeChapterID,
		&state.ResumeChapterSlug,
		&state.ResumeChapterNumber,
		&state.FurthestChapterID,
		&state.FurthestChapterNumber,
		&state.LastPage,
		&state.ScrollPosition,
		&state.UpdatedAt,
		&state.Revision,
		&state.LastOpenedAt,
		&state.SessionGeneration,
		&readIDs,
		&completedIDs,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	state.ReadChapterIDs = readIDs
	state.CompletedChapterIDs = completedIDs
	return &state, nil
}

type ProgressUpdate struct {
	UserID          string
	SeriesID        string
	ChapterID       string
	LastPage        int
	ScrollPosition  float64
	UpdatedAt       time.Time
	SourceMessageID string
}

type BatchResult struct {
	Applied  bool
	Valid    bool
	Revision int64
}

const progressUpsertSQL = `WITH target AS (
    SELECT EXISTS (SELECT 1 FROM users u WHERE u.id=$1::uuid)
       AND EXISTS (
           SELECT 1 FROM chapters c
           WHERE c.id=$3::uuid AND c.series_id=$2::uuid
       ) AS valid
), upserted AS (
    INSERT INTO reading_progress
        (user_id, series_id, chapter_id, last_page, scroll_position, updated_at, last_opened_at)
    SELECT $1::uuid, $2::uuid, $3::uuid, $4, $5, $6::timestamptz, $6::timestamptz
    FROM target
    WHERE target.valid
    ON CONFLICT (user_id, series_id)
	    DO UPDATE SET
        chapter_id = EXCLUDED.chapter_id,
        last_page = EXCLUDED.last_page,
        scroll_position = EXCLUDED.scroll_position,
	        updated_at = EXCLUDED.updated_at,
        last_opened_at = EXCLUDED.last_opened_at,
	        revision = reading_progress.revision + 1
    WHERE reading_progress.session_generation = 0 AND reading_progress.updated_at < EXCLUDED.updated_at
    RETURNING revision
)
SELECT target.valid,
       EXISTS (SELECT 1 FROM upserted) AS applied,
       COALESCE(
           (SELECT revision FROM upserted),
           (SELECT revision FROM reading_progress WHERE user_id=$1::uuid AND series_id=$2::uuid),
           0
       ) AS revision
FROM target`

const chapterReadUpsertSQL = `INSERT INTO chapter_reads(
    user_id, series_id, chapter_id, first_read_at, last_read_at,
    last_page, completed, completed_at, provenance
)
SELECT $1::uuid,$2::uuid,$3::uuid,$6::timestamptz,$6::timestamptz,
       $4,
       CASE WHEN COALESCE(c.page_count,0) > 0 AND $4 >= c.page_count THEN TRUE ELSE FALSE END,
       CASE WHEN COALESCE(c.page_count,0) > 0 AND $4 >= c.page_count THEN $6::timestamptz ELSE NULL END,
       'legacy'
FROM chapters c
WHERE c.id=$3::uuid AND c.series_id=$2::uuid
ON CONFLICT (user_id, chapter_id)
DO UPDATE SET
    first_read_at = CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.first_read_at
                        ELSE LEAST(chapter_reads.first_read_at, EXCLUDED.first_read_at) END,
    last_read_at = CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.last_read_at
                       ELSE GREATEST(chapter_reads.last_read_at, EXCLUDED.last_read_at) END,
    last_page = GREATEST(chapter_reads.last_page, EXCLUDED.last_page),
    provenance = CASE WHEN chapter_reads.provenance='migrated_reach' THEN 'legacy' ELSE chapter_reads.provenance END,
    completed = chapter_reads.completed OR EXCLUDED.completed,
    completed_at = CASE
        WHEN chapter_reads.completed_at IS NOT NULL THEN chapter_reads.completed_at
        ELSE EXCLUDED.completed_at
    END`

// UpsertBatch drains progress messages produced by the previous write-behind
// implementation in one database transaction and at most
// two pgx wire batches regardless of item count. This keeps a logout/page-exit
// wave from turning into one transaction and several network round trips per
// progress event while preserving stale-delivery and outbox semantics.
func (s *Store) UpsertBatch(ctx context.Context, updates []ProgressUpdate) ([]BatchResult, error) {
	results := make([]BatchResult, len(updates))
	if len(updates) == 0 {
		return results, nil
	}

	tx, err := s.db.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	var writes pgx.Batch
	for _, update := range updates {
		writes.Queue(
			progressUpsertSQL,
			update.UserID,
			update.SeriesID,
			update.ChapterID,
			update.LastPage,
			update.ScrollPosition,
			update.UpdatedAt.UTC(),
		)
	}
	writeResults := tx.SendBatch(ctx, &writes)
	for i := range updates {
		if err := writeResults.QueryRow().Scan(&results[i].Valid, &results[i].Applied, &results[i].Revision); err != nil {
			_ = writeResults.Close()
			return nil, err
		}
	}
	if err := writeResults.Close(); err != nil {
		return nil, err
	}

	type followup struct {
		index int
		kind  string
	}
	followups := make([]followup, 0, len(updates)*3)
	var second pgx.Batch
	for i, update := range updates {
		if !results[i].Valid {
			continue
		}

		// The chapter ledger is independent from whether this update wins the
		// single resume row. A delayed update still records that chapter as read.
		second.Queue(
			chapterReadUpsertSQL,
			update.UserID, update.SeriesID, update.ChapterID, update.LastPage, update.ScrollPosition, update.UpdatedAt.UTC(),
		)
		followups = append(followups, followup{index: i, kind: "exec"})

		if !results[i].Applied {
			continue
		}
		args, err := progressUpdatedEventArgs(
			update.UserID,
			update.SeriesID,
			update.ChapterID,
			update.LastPage,
			update.ScrollPosition,
			update.UpdatedAt,
			results[i].Revision,
			update.SourceMessageID,
		)
		if err != nil {
			return nil, err
		}
		second.Queue(enqueueProgressUpdatedSQL, args...)
		followups = append(followups, followup{index: i, kind: "event"})
	}

	if len(followups) > 0 {
		secondResults := tx.SendBatch(ctx, &second)
		for _, op := range followups {
			switch op.kind {
			case "exec":
				if _, err := secondResults.Exec(); err != nil {
					_ = secondResults.Close()
					return nil, err
				}
			case "event":
				var eventID string
				if err := secondResults.QueryRow().Scan(&eventID); err != nil {
					_ = secondResults.Close()
					return nil, err
				}
				if eventID == "" {
					_ = secondResults.Close()
					return nil, errors.New("failed to enqueue progress.updated outbox event")
				}
			}
		}
		if err := secondResults.Close(); err != nil {
			return nil, err
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return results, nil
}
