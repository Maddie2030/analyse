package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"time"

	"github.com/jackc/pgx/v5"
)

const MaxReadingOrder int64 = 9007199254740991

var ErrInvalidCommand = errors.New("invalid reading command")

type OpenCommand struct {
	CommandID        string `json:"command_id"`
	ExpectedRevision int64  `json:"expected_revision"`
	RequestID        string `json:"-"`
	OperationID      string `json:"-"`
}

type CommitCommand struct {
	CommandID         string  `json:"command_id"`
	RequestID         string  `json:"-"`
	OperationID       string  `json:"-"`
	SessionGeneration int64   `json:"session_generation"`
	CommandSequence   int64   `json:"command_sequence"`
	LastPage          int     `json:"last_page"`
	ScrollPosition    float64 `json:"scroll_position"`
	Completed         bool    `json:"completed"`
	CompletedPage     int     `json:"completed_page"`
}

type CommandResult struct {
	Progress
	Accepted  bool   `json:"accepted"`
	Duplicate bool   `json:"duplicate"`
	Code      string `json:"code"`
	CommandID string `json:"command_id"`
}

type chapterCommandState struct {
	SessionGeneration int64
	Sequence          int64
	CommandID         string
	CommandHash       string
	OpenCommandID     string
	OpenRevision      int64
	ResumePage        int
	ResumeScroll      float64
}

const progressColumns = `series_id::text, COALESCE(chapter_id::text, ''), last_page,
    scroll_position, updated_at, revision, last_opened_at, session_generation, command_sequence`

const currentProgressSQL = `SELECT ` + progressColumns + ` FROM reading_progress
    WHERE user_id=$1::uuid AND series_id=$2::uuid`

func scanProgress(row pgx.Row) (*Progress, error) {
	var p Progress
	err := row.Scan(&p.SeriesID, &p.ChapterID, &p.LastPage, &p.ScrollPosition,
		&p.UpdatedAt, &p.Revision, &p.LastOpenedAt, &p.SessionGeneration, &p.CommandSequence)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// All command writers serialize on the aggregate, including the first open
// when no resume row exists. Hash collisions only serialize unrelated readers;
// they cannot let either caller operate on the other's rows.
func (s *Store) beginReadingCommand(ctx context.Context, userID string, target Target) (pgx.Tx, Target, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return nil, target, err
	}
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1, 0))`, userID+":"+target.SeriesID); err == nil {
		err = tx.QueryRow(ctx, `SELECT COALESCE(page_count, 0) FROM chapters
            WHERE id=$1::uuid AND series_id=$2::uuid AND status='published' FOR KEY SHARE`,
			target.ChapterID, target.SeriesID).Scan(&target.PageCount)
	}
	if err != nil {
		_ = tx.Rollback(ctx)
		if errors.Is(err, pgx.ErrNoRows) {
			err = ErrNotFound
		}
		return nil, target, err
	}
	return tx, target, nil
}

func loadChapterCommand(ctx context.Context, tx pgx.Tx, userID string, target Target) (*chapterCommandState, error) {
	var c chapterCommandState
	err := tx.QueryRow(ctx, `SELECT session_generation, command_sequence,
        COALESCE(command_id::text, ''), COALESCE(command_hash, ''),
        COALESCE(open_command_id::text, ''), COALESCE(open_expected_revision, 0),
        COALESCE(resume_page, 1), COALESCE(resume_scroll_position, 0)
        FROM chapter_reads WHERE user_id=$1::uuid AND series_id=$2::uuid AND chapter_id=$3::uuid FOR UPDATE`,
		userID, target.SeriesID, target.ChapterID).Scan(&c.SessionGeneration, &c.Sequence,
		&c.CommandID, &c.CommandHash, &c.OpenCommandID, &c.OpenRevision, &c.ResumePage, &c.ResumeScroll)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &c, nil
}

func commandResult(p *Progress, target Target, commandID string) CommandResult {
	result := CommandResult{CommandID: commandID}
	if p != nil {
		result.Progress = *p
	} else {
		result.Progress = Progress{SeriesID: target.SeriesID, ChapterID: target.ChapterID, LastPage: 1}
	}
	return result
}

func persistReadingResult(ctx context.Context, tx pgx.Tx, userID string, p Progress, metadata EventMetadata) error {
	_, err := tx.Exec(ctx, `INSERT INTO reading_progress
        (user_id, series_id, chapter_id, last_page, scroll_position, updated_at,
         revision, last_opened_at, session_generation, command_sequence)
        VALUES ($1::uuid,$2::uuid,NULLIF($3,'')::uuid,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (user_id, series_id) DO UPDATE SET
            chapter_id=EXCLUDED.chapter_id, last_page=EXCLUDED.last_page,
            scroll_position=EXCLUDED.scroll_position, updated_at=EXCLUDED.updated_at,
            revision=EXCLUDED.revision, last_opened_at=EXCLUDED.last_opened_at,
            session_generation=EXCLUDED.session_generation, command_sequence=EXCLUDED.command_sequence`,
		userID, p.SeriesID, p.ChapterID, p.LastPage, p.ScrollPosition, p.UpdatedAt,
		p.Revision, p.LastOpenedAt, p.SessionGeneration, p.CommandSequence)
	if err != nil {
		return err
	}
	// Even a ledger-only update after deletion of the resume target advances the
	// projection revision and emits its event. v2 represents that target as null.
	_, err = enqueueProgressUpdatedTx(ctx, tx, userID, p.SeriesID, p.ChapterID,
		p.LastPage, p.ScrollPosition, p.UpdatedAt, p.Revision, "", metadata)
	return err
}

func (s *Store) OpenReadingState(ctx context.Context, userID string, target Target, command OpenCommand) (CommandResult, error) {
	if command.ExpectedRevision < 0 || command.ExpectedRevision >= MaxReadingOrder {
		return CommandResult{}, ErrInvalidCommand
	}
	tx, target, err := s.beginReadingCommand(ctx, userID, target)
	if err != nil {
		return CommandResult{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	p, err := scanProgress(tx.QueryRow(ctx, currentProgressSQL+` FOR UPDATE`, userID, target.SeriesID))
	if err != nil {
		return CommandResult{}, err
	}
	c, err := loadChapterCommand(ctx, tx, userID, target)
	if err != nil {
		return CommandResult{}, err
	}
	result := commandResult(p, target, command.CommandID)
	if c != nil && c.OpenCommandID == command.CommandID {
		result.Code = "command_conflict"
		if c.OpenRevision == command.ExpectedRevision {
			result.Duplicate = true
			result.Code = "stale_session"
			if p != nil && p.ChapterID == target.ChapterID && p.SessionGeneration == c.SessionGeneration {
				result.Accepted, result.Code = true, "duplicate"
			}
		}
		return result, nil
	}
	if result.Revision != command.ExpectedRevision {
		result.Code = "revision_conflict"
		return result, nil
	}
	var reused bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM chapter_reads
        WHERE user_id=$1::uuid AND series_id=$2::uuid AND open_command_id=$3::uuid)`,
		userID, target.SeriesID, command.CommandID).Scan(&reused); err != nil {
		return CommandResult{}, err
	}
	if reused {
		result.Code = "command_conflict"
		return result, nil
	}
	if result.Revision >= MaxReadingOrder || result.SessionGeneration >= MaxReadingOrder {
		return CommandResult{}, ErrInvalidCommand
	}
	page, scroll := 1, 0.0
	if p != nil && p.ChapterID == target.ChapterID {
		page, scroll = p.LastPage, p.ScrollPosition
	} else if c != nil {
		page, scroll = c.ResumePage, c.ResumeScroll
	}
	if target.PageCount > 0 && page > target.PageCount {
		page = target.PageCount
	}
	var now time.Time
	if err := tx.QueryRow(ctx, `SELECT clock_timestamp()`).Scan(&now); err != nil {
		return CommandResult{}, err
	}
	result.Progress = Progress{SeriesID: target.SeriesID, ChapterID: target.ChapterID,
		LastPage: page, ScrollPosition: scroll, UpdatedAt: now, LastOpenedAt: now,
		Revision: result.Revision + 1, SessionGeneration: result.SessionGeneration + 1}
	_, err = tx.Exec(ctx, `INSERT INTO chapter_reads
        (user_id,series_id,chapter_id,first_read_at,last_read_at,last_page,resume_page,
         resume_scroll_position,session_generation,command_sequence,open_command_id,open_expected_revision,provenance)
        VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$4,$5,$5,$6,$7,0,$8::uuid,$9,'observed')
        ON CONFLICT (user_id,chapter_id) DO UPDATE SET
            first_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.first_read_at
                               ELSE chapter_reads.first_read_at END,
            last_read_at=CASE WHEN chapter_reads.provenance='migrated_reach' THEN EXCLUDED.last_read_at
                              ELSE GREATEST(chapter_reads.last_read_at,EXCLUDED.last_read_at) END,
            last_page=GREATEST(chapter_reads.last_page,EXCLUDED.last_page),
            resume_page=EXCLUDED.resume_page,resume_scroll_position=EXCLUDED.resume_scroll_position,
            session_generation=EXCLUDED.session_generation,command_sequence=0,
            command_id=NULL,command_hash=NULL,open_command_id=EXCLUDED.open_command_id,
            open_expected_revision=EXCLUDED.open_expected_revision,provenance='observed'`,
		userID, target.SeriesID, target.ChapterID, now, page, scroll,
		result.SessionGeneration, command.CommandID, command.ExpectedRevision)
	if err != nil {
		return CommandResult{}, err
	}
	if err := persistReadingResult(ctx, tx, userID, result.Progress, EventMetadata{RequestID: command.RequestID, OperationID: command.OperationID}); err != nil {
		return CommandResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return CommandResult{}, err
	}
	result.Accepted, result.Code = true, "accepted"
	return result, nil
}

func validCheckpoint(command CommitCommand, pageCount int) bool {
	return command.SessionGeneration > 0 && command.SessionGeneration <= MaxReadingOrder &&
		command.CommandSequence > 0 && command.CommandSequence <= MaxReadingOrder &&
		command.LastPage >= 1 && int64(command.LastPage) <= MaxReadingOrder &&
		!math.IsNaN(command.ScrollPosition) && !math.IsInf(command.ScrollPosition, 0) &&
		command.ScrollPosition >= 0 && command.ScrollPosition <= 1 &&
		((!command.Completed && command.CompletedPage == 0) ||
			(command.Completed && command.CompletedPage > 0 &&
				int64(command.CompletedPage) <= MaxReadingOrder &&
				pageCount > 0 && command.CompletedPage == pageCount))
}

func (s *Store) CommitReadingState(ctx context.Context, userID string, target Target, command CommitCommand) (CommandResult, error) {
	tx, target, err := s.beginReadingCommand(ctx, userID, target)
	if err != nil {
		return CommandResult{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if !validCheckpoint(command, target.PageCount) {
		return CommandResult{}, ErrInvalidCommand
	}
	p, err := scanProgress(tx.QueryRow(ctx, currentProgressSQL+` FOR UPDATE`, userID, target.SeriesID))
	if err != nil {
		return CommandResult{}, err
	}
	c, err := loadChapterCommand(ctx, tx, userID, target)
	if err != nil {
		return CommandResult{}, err
	}
	result := commandResult(p, target, command.CommandID)
	if p == nil || c == nil || c.SessionGeneration != command.SessionGeneration {
		result.Code = "stale_session"
		return result, nil
	}
	encoded, err := json.Marshal(command)
	if err != nil {
		return CommandResult{}, err
	}
	sum := sha256.Sum256(encoded)
	hash := hex.EncodeToString(sum[:])
	checkpointPage := command.LastPage
	if target.PageCount > 0 && checkpointPage > target.PageCount {
		checkpointPage = target.PageCount
	}
	active := p.ChapterID == target.ChapterID && p.SessionGeneration == command.SessionGeneration
	if command.CommandSequence < c.Sequence {
		result.Code = "stale_sequence"
		return result, nil
	}
	if command.CommandSequence == c.Sequence {
		result.Code = "command_conflict"
		if c.CommandID == command.CommandID && c.CommandHash == hash {
			result.Duplicate = true
			result.Code = "stale_session"
			if active {
				result.Accepted, result.Code = true, "duplicate"
			}
		}
		return result, nil
	}
	if c.CommandID == command.CommandID || c.OpenCommandID == command.CommandID {
		result.Code = "command_conflict"
		return result, nil
	}
	if p.Revision >= MaxReadingOrder {
		return CommandResult{}, ErrInvalidCommand
	}
	var now time.Time
	if err := tx.QueryRow(ctx, `SELECT clock_timestamp()`).Scan(&now); err != nil {
		return CommandResult{}, err
	}
	// This exact chapter session remains independently useful after the user has
	// opened another chapter. Its checkpoint/completion cannot select resume.
	_, err = tx.Exec(ctx, `UPDATE chapter_reads SET
        last_read_at=GREATEST(last_read_at,$4),last_page=GREATEST(last_page,$5,$10),
        resume_page=$5,resume_scroll_position=$6,command_sequence=$7,
        command_id=$8::uuid,command_hash=$9,completed=completed OR $11,
        completed_at=CASE WHEN completed_at IS NOT NULL THEN completed_at WHEN $11 THEN $4 ELSE NULL END
        WHERE user_id=$1::uuid AND series_id=$2::uuid AND chapter_id=$3::uuid`,
		userID, target.SeriesID, target.ChapterID, now, checkpointPage,
		command.ScrollPosition, command.CommandSequence, command.CommandID, hash,
		command.CompletedPage, command.Completed)
	if err != nil {
		return CommandResult{}, err
	}
	result.Revision++
	result.UpdatedAt = now
	result.Code = "stale_session"
	if active {
		result.LastPage, result.ScrollPosition = checkpointPage, command.ScrollPosition
		result.CommandSequence = command.CommandSequence
		result.Accepted, result.Code = true, "accepted"
	}
	if err := persistReadingResult(ctx, tx, userID, result.Progress, EventMetadata{RequestID: command.RequestID, OperationID: command.OperationID}); err != nil {
		return CommandResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return CommandResult{}, err
	}
	return result, nil
}
