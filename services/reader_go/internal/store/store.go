package store

import (
	"context"
	"errors"
	"strings"
	"sync"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type Store struct {
	db *pgxpool.Pool
}

func New(db *pgxpool.Pool) *Store {
	return &Store{db: db}
}

type ChapterManifest struct {
	SeriesID      string
	SeriesTitle   string
	SeriesSlug    string
	ChapterID     string
	ChapterNumber float64
	ChapterTitle  *string
	ChapterSlug   string
	PageCount     int
}

type Page struct {
	PageNumber          int
	ImagePath           string
	Width               *int
	Height              *int
	ResponsiveImagePath *string
	ResponsiveWidth     *int
	ResponsiveHeight    *int
	EncodingVersion     int
	EncodingRows        *int
	EncodingColumns     *int
	EncodingSeed        *string
}

type ChapterLink struct {
	Slug          string  `json:"slug"`
	ChapterNumber float64 `json:"chapter_number"`
}

func (s *Store) ReaderChapter(
	ctx context.Context,
	seriesSlug string,
	chapterSlug string,
) (ChapterManifest, []Page, *ChapterLink, *ChapterLink, error) {
	var manifest ChapterManifest

	err := s.db.QueryRow(ctx, `
		SELECT
			s.id::text,
			s.title,
			s.slug,
			c.id::text,
			c.chapter_number::float8,
			c.title,
			c.slug,
			COALESCE(c.page_count, 0)
		FROM series s
		JOIN chapters c ON c.series_id = s.id
		WHERE s.slug = $1
		  AND c.slug = $2
		  AND c.status = 'published'
	`, seriesSlug, chapterSlug).Scan(
		&manifest.SeriesID,
		&manifest.SeriesTitle,
		&manifest.SeriesSlug,
		&manifest.ChapterID,
		&manifest.ChapterNumber,
		&manifest.ChapterTitle,
		&manifest.ChapterSlug,
		&manifest.PageCount,
	)

	if errors.Is(err, pgx.ErrNoRows) {
		return ChapterManifest{}, nil, nil, nil, ErrNotFound
	}
	if err != nil {
		return ChapterManifest{}, nil, nil, nil, err
	}

	var (
		pages    []Page
		prev     *ChapterLink
		next     *ChapterLink
		pagesErr error
		prevErr  error
		nextErr  error
		wg       sync.WaitGroup
	)

	// These reads depend only on the manifest and are independent. pgxpool is
	// safe for concurrent use, so let PostgreSQL/connection-pool scheduling
	// overlap page retrieval with the two small neighbour index seeks.
	wg.Add(3)
	go func() {
		defer wg.Done()
		pages, pagesErr = s.fetchPages(ctx, manifest.ChapterID, manifest.PageCount)
	}()
	go func() {
		defer wg.Done()
		prev, prevErr = s.chapterLink(ctx, manifest.SeriesID, manifest.ChapterNumber, true)
	}()
	go func() {
		defer wg.Done()
		next, nextErr = s.chapterLink(ctx, manifest.SeriesID, manifest.ChapterNumber, false)
	}()
	wg.Wait()

	if pagesErr != nil {
		return ChapterManifest{}, nil, nil, nil, pagesErr
	}
	if prevErr != nil {
		return ChapterManifest{}, nil, nil, nil, prevErr
	}
	if nextErr != nil {
		return ChapterManifest{}, nil, nil, nil, nextErr
	}

	return manifest, pages, prev, next, nil
}

func (s *Store) fetchPages(ctx context.Context, chapterID string, capacity int) ([]Page, error) {
	rows, err := s.db.Query(ctx, `
		SELECT
			page_number,
			image_path,
			width,
			height,
			responsive_image_path,
			responsive_width,
			responsive_height,
			COALESCE(encoding_version, 4),
			encoding_rows,
			encoding_columns,
			encoding_seed
		FROM pages
		WHERE chapter_id = $1::uuid
		ORDER BY page_number
	`, chapterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	pages := make([]Page, 0, capacity)
	for rows.Next() {
		var p Page
		if err := rows.Scan(
			&p.PageNumber,
			&p.ImagePath,
			&p.Width,
			&p.Height,
			&p.ResponsiveImagePath,
			&p.ResponsiveWidth,
			&p.ResponsiveHeight,
			&p.EncodingVersion,
			&p.EncodingRows,
			&p.EncodingColumns,
			&p.EncodingSeed,
		); err != nil {
			return nil, err
		}
		pages = append(pages, p)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return pages, nil
}

func (s *Store) ReaderPagePath(
	ctx context.Context,
	seriesSlug string,
	chapterSlug string,
	pageNumber int,
) (string, error) {
	var path string
	err := s.db.QueryRow(ctx, `
		SELECT p.image_path
		FROM pages p
		JOIN chapters c ON c.id = p.chapter_id
		JOIN series s ON s.id = c.series_id
		WHERE s.slug = $1
		  AND c.slug = $2
		  AND c.status = 'published'
		  AND p.page_number = $3
		LIMIT 1
	`, seriesSlug, chapterSlug, pageNumber).Scan(&path)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	return path, err
}

// ReaderPageAsset resolves the canonical published page metadata used by the
// mobile adapter. The adapter never accepts an arbitrary storage path from the
// client; it derives the path from the same database row that powers the web
// reader manifest.
func (s *Store) ReaderPageAsset(
	ctx context.Context,
	seriesSlug string,
	chapterSlug string,
	pageNumber int,
) (Page, error) {
	var p Page
	err := s.db.QueryRow(ctx, `
		SELECT
			p.page_number,
			p.image_path,
			p.width,
			p.height,
			p.responsive_image_path,
			p.responsive_width,
			p.responsive_height,
			COALESCE(p.encoding_version, 4),
			p.encoding_rows,
			p.encoding_columns,
			p.encoding_seed
		FROM pages p
		JOIN chapters c ON c.id = p.chapter_id
		JOIN series s ON s.id = c.series_id
		WHERE s.slug = $1
		  AND c.slug = $2
		  AND c.status = 'published'
		  AND p.page_number = $3
		LIMIT 1
	`, seriesSlug, chapterSlug, pageNumber).Scan(
		&p.PageNumber,
		&p.ImagePath,
		&p.Width,
		&p.Height,
		&p.ResponsiveImagePath,
		&p.ResponsiveWidth,
		&p.ResponsiveHeight,
		&p.EncodingVersion,
		&p.EncodingRows,
		&p.EncodingColumns,
		&p.EncodingSeed,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return Page{}, ErrNotFound
	}
	return p, err
}

func (s *Store) chapterLink(
	ctx context.Context,
	seriesID string,
	chapterNumber float64,
	previous bool,
) (*ChapterLink, error) {
	operator := ">"
	order := "ASC"
	if previous {
		operator = "<"
		order = "DESC"
	}

	query := `
		SELECT slug, chapter_number::float8
		FROM chapters
		WHERE series_id = $1::uuid
		  AND chapter_number ` + operator + ` $2
		  AND status = 'published'
		ORDER BY chapter_number ` + order + `
		LIMIT 1
	`

	var link ChapterLink
	err := s.db.QueryRow(ctx, query, seriesID, chapterNumber).Scan(
		&link.Slug,
		&link.ChapterNumber,
	)

	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &link, nil
}

// ChapterGrantPaths returns the exact current page allow-list for a published
// chapter. It is used to mint one chapter-scoped image grant without relying on
// mutable slugs or directory-prefix assumptions.
func (s *Store) ChapterGrantPaths(ctx context.Context, seriesSlug, chapterSlug string) (string, []string, error) {
	var chapterID string
	err := s.db.QueryRow(ctx, `
		SELECT c.id::text
		FROM chapters c
		JOIN series s ON s.id = c.series_id
		WHERE s.slug=$1 AND c.slug=$2 AND c.status='published'
	`, seriesSlug, chapterSlug).Scan(&chapterID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, ErrNotFound
	}
	if err != nil {
		return "", nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT image_path, responsive_image_path FROM pages WHERE chapter_id=$1::uuid ORDER BY page_number`, chapterID)
	if err != nil {
		return "", nil, err
	}
	defer rows.Close()
	paths := make([]string, 0)
	for rows.Next() {
		var path string
		var responsivePath *string
		if err := rows.Scan(&path, &responsivePath); err != nil {
			return "", nil, err
		}
		paths = append(paths, path)
		if responsivePath != nil && strings.TrimSpace(*responsivePath) != "" {
			paths = append(paths, *responsivePath)
		}
	}
	if err := rows.Err(); err != nil {
		return "", nil, err
	}
	return chapterID, paths, nil
}
