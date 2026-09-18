package outbox

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct {
	db *pgxpool.Pool
}

type Event struct {
	EventID       string
	Topic         string
	EventType     string
	EventVersion  int
	AggregateType string
	AggregateID   string
	PartitionKey  string
	Producer      string
	CorrelationID string
	CausationID   string
	OccurredAt    time.Time
	Payload       json.RawMessage
	Headers       json.RawMessage
	AttemptCount  int
}

func New(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

func (s *Store) Ping(ctx context.Context) error {
	return s.db.Ping(ctx)
}

func (s *Store) Claim(
	ctx context.Context,
	workerID string,
	batchSize int,
	staleAfter time.Duration,
) ([]Event, error) {
	rows, err := s.db.Query(
		ctx,
		`WITH candidates AS (
		    SELECT event_id
		      FROM event_outbox
		     WHERE published_at IS NULL
		       AND available_at <= NOW()
		       AND (
		            locked_at IS NULL
		            OR locked_at < NOW() - make_interval(secs => $3::double precision)
		       )
		     ORDER BY available_at, created_at, event_id
		     FOR UPDATE SKIP LOCKED
		     LIMIT $2
		), claimed AS (
		    UPDATE event_outbox e
		       SET locked_at = NOW(),
		           locked_by = $1,
		           attempt_count = e.attempt_count + 1
		      FROM candidates c
		     WHERE e.event_id = c.event_id
		 RETURNING e.event_id::text,
		           e.topic,
		           e.event_type,
		           e.event_version,
		           e.aggregate_type,
		           e.aggregate_id,
		           e.partition_key,
		           e.producer,
		           COALESCE(e.correlation_id::text, ''),
		           COALESCE(e.causation_id::text, ''),
		           e.occurred_at,
		           e.payload,
		           e.headers,
		           e.attempt_count
		)
		SELECT * FROM claimed`,
		workerID,
		batchSize,
		staleAfter.Seconds(),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]Event, 0, batchSize)
	for rows.Next() {
		var event Event
		if err := rows.Scan(
			&event.EventID,
			&event.Topic,
			&event.EventType,
			&event.EventVersion,
			&event.AggregateType,
			&event.AggregateID,
			&event.PartitionKey,
			&event.Producer,
			&event.CorrelationID,
			&event.CausationID,
			&event.OccurredAt,
			&event.Payload,
			&event.Headers,
			&event.AttemptCount,
		); err != nil {
			return nil, err
		}
		events = append(events, event)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return events, nil
}

func (s *Store) MarkPublished(
	ctx context.Context,
	eventID string,
	workerID string,
) error {
	tag, err := s.db.Exec(
		ctx,
		`UPDATE event_outbox
		    SET published_at = NOW(),
		        locked_at = NULL,
		        locked_by = NULL,
		        last_error = NULL
		  WHERE event_id = $1::uuid
		    AND published_at IS NULL
		    AND locked_by = $2`,
		eventID,
		workerID,
	)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return errors.New("outbox event publish acknowledgement lost claim ownership")
	}
	return nil
}

func (s *Store) MarkFailed(
	ctx context.Context,
	eventID string,
	workerID string,
	nextAttempt time.Time,
	lastError string,
) error {
	tag, err := s.db.Exec(
		ctx,
		`UPDATE event_outbox
		    SET available_at = $3,
		        last_error = $4,
		        locked_at = NULL,
		        locked_by = NULL
		  WHERE event_id = $1::uuid
		    AND published_at IS NULL
		    AND locked_by = $2`,
		eventID,
		workerID,
		nextAttempt,
		lastError,
	)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return errors.New("outbox event failure update lost claim ownership")
	}
	return nil
}

func (s *Store) ReleaseWorkerLocks(
	ctx context.Context,
	workerID string,
) error {
	_, err := s.db.Exec(
		ctx,
		`UPDATE event_outbox
		    SET locked_at = NULL,
		        locked_by = NULL
		  WHERE published_at IS NULL
		    AND locked_by = $1`,
		workerID,
	)
	return err
}
