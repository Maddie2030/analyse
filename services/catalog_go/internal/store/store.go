package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"mreader/catalog/internal/model"
)

var ErrNotFound = errors.New("not found")
var ErrConflict = errors.New("conflict")
var ErrInvalidReference = errors.New("invalid reference")
var ErrNoPages = errors.New("chapter has no pages")
var ErrPublicationRequiresMedia = errors.New("chapter publication requires Media evidence")

func enqueueCleanupTxWithID(ctx context.Context, tx pgx.Tx, entityType, entityID string, payload map[string]any) (string, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	var jobID string
	err = tx.QueryRow(ctx, `
		INSERT INTO lifecycle_cleanup_jobs(entity_type, entity_id, payload)
		VALUES($1, $2::uuid, $3::jsonb)
		RETURNING id::text
	`, entityType, entityID, raw).Scan(&jobID)
	return jobID, err
}

func enqueueCleanupTx(ctx context.Context, tx pgx.Tx, entityType, entityID string, payload map[string]any) error {
	_, err := enqueueCleanupTxWithID(ctx, tx, entityType, entityID, payload)
	return err
}

func appendUniqueString(values []string, value string) []string {
	value = strings.TrimSpace(strings.TrimLeft(value, "/"))
	if value == "" || strings.Contains(value, "..") {
		return values
	}
	for _, existing := range values {
		if existing == value {
			return values
		}
	}
	return append(values, value)
}

type cleanupObjectRef struct {
	Path       string `json:"path"`
	Generation int64  `json:"generation"`
	Kind       string `json:"kind"`
}

func appendCleanupObjectRef(values []cleanupObjectRef, path string, generation int64, kind string) []cleanupObjectRef {
	path = strings.TrimSpace(strings.TrimLeft(path, "/"))
	kind = strings.TrimSpace(kind)
	if path == "" || strings.Contains(path, "..") || kind == "" || generation < 0 {
		return values
	}
	for _, existing := range values {
		if existing.Path == path && existing.Generation == generation && existing.Kind == kind {
			return values
		}
	}
	return append(values, cleanupObjectRef{Path: path, Generation: generation, Kind: kind})
}

func cleanupObjectPaths(values []cleanupObjectRef) []string {
	paths := make([]string, 0, len(values))
	for _, value := range values {
		paths = appendUniqueString(paths, value.Path)
	}
	return paths
}

type Store struct{ db *pgxpool.Pool }

func New(db *pgxpool.Pool) *Store { return &Store{db: db} }

func (s *Store) IsActiveAdmin(ctx context.Context, actorID string) (bool, error) {
	var authorized bool
	err := s.db.QueryRow(ctx, `
		SELECT EXISTS (
			SELECT 1
			FROM users
			WHERE id=$1::uuid
			  AND is_active=TRUE
			  AND role='admin'
		)`, actorID,
	).Scan(&authorized)
	if err != nil {
		return false, err
	}
	return authorized, nil
}

func (s *Store) Genres(ctx context.Context) ([]model.Genre, error) {
	rows, err := s.db.Query(ctx, `
		SELECT g.id, g.name
		FROM genres g
		WHERE EXISTS (
			SELECT 1
			FROM series_genres sg
			JOIN series s ON s.id = sg.series_id
			WHERE sg.genre_id = g.id
		)
		ORDER BY g.name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Genre, 0)
	for rows.Next() {
		var x model.Genre
		if err := rows.Scan(&x.ID, &x.Name); err != nil {
			return nil, err
		}
		out = append(out, x)
	}
	return out, rows.Err()
}

func (s *Store) Tags(ctx context.Context) ([]model.Tag, error) {
	rows, err := s.db.Query(ctx, `
		SELECT t.id, t.name
		FROM tags t
		WHERE EXISTS (
			SELECT 1
			FROM series_tags st
			JOIN series s ON s.id = st.series_id
			WHERE st.tag_id = t.id
		)
		ORDER BY t.name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Tag, 0)
	for rows.Next() {
		var x model.Tag
		if err := rows.Scan(&x.ID, &x.Name); err != nil {
			return nil, err
		}
		out = append(out, x)
	}
	return out, rows.Err()
}

type SeriesFilter struct {
	Search, Status string
	Sort           string
	GenreIDs       []int
	TagIDs         []int
	MinRating      *float64
	Offset, Limit  int
}

func (s *Store) SeriesList(ctx context.Context, f SeriesFilter) ([]model.Series, error) {
	args := []any{}
	where := []string{}
	idx := 1

	if f.Search != "" {
		where = append(
			where,
			fmt.Sprintf(
				"(s.title ILIKE '%%' || $%d || '%%' OR s.title %% $%d OR s.description %% $%d)",
				idx,
				idx,
				idx,
			),
		)
		args = append(args, f.Search)
		idx++
	}

	if f.Status != "" {
		where = append(where, fmt.Sprintf("s.status=$%d", idx))
		args = append(args, f.Status)
		idx++
	}

	for _, genreID := range f.GenreIDs {
		where = append(
			where,
			fmt.Sprintf(
				"EXISTS (SELECT 1 FROM series_genres sg WHERE sg.series_id=s.id AND sg.genre_id=$%d)",
				idx,
			),
		)
		args = append(args, genreID)
		idx++
	}

	for _, tagID := range f.TagIDs {
		where = append(
			where,
			fmt.Sprintf(
				"EXISTS (SELECT 1 FROM series_tags st WHERE st.series_id=s.id AND st.tag_id=$%d)",
				idx,
			),
		)
		args = append(args, tagID)
		idx++
	}

	if f.MinRating != nil {
		where = append(
			where,
			fmt.Sprintf(
				"(SELECT AVG(r.rating)::float8 FROM series_ratings r WHERE r.series_id=s.id) >= $%d",
				idx,
			),
		)
		args = append(args, *f.MinRating)
		idx++
	}

	q := `
		SELECT
			s.id::text,
			s.title,
			s.slug,
			s.description,
			s.cover_image_path,
			s.status,
			s.created_at,
			s.updated_at
		FROM series s`

	if len(where) > 0 {
		q += " WHERE " + strings.Join(where, " AND ")
	}

	switch f.Sort {
	case "relevance":
		if f.Search != "" {
			q += " ORDER BY CASE WHEN s.title ILIKE $1 || '%' THEN 0 ELSE 1 END, similarity(s.title,$1) DESC, s.updated_at DESC"
		} else {
			q += " ORDER BY s.updated_at DESC"
		}
	case "newest":
		q += " ORDER BY s.created_at DESC, s.updated_at DESC"
	case "title":
		q += " ORDER BY LOWER(s.title) ASC, s.updated_at DESC"
	case "rating":
		q += " ORDER BY COALESCE((SELECT AVG(sr.rating)::float8 FROM series_ratings sr WHERE sr.series_id=s.id),0) DESC, s.updated_at DESC"
	case "popular":
		q += " ORDER BY (SELECT COUNT(*) FROM bookmarks b WHERE b.series_id=s.id) DESC, s.updated_at DESC"
	default:
		q += " ORDER BY s.updated_at DESC"
	}

	q += fmt.Sprintf(" LIMIT $%d OFFSET $%d", idx, idx+1)
	args = append(args, f.Limit, f.Offset)

	rows, err := s.db.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]model.Series, 0)
	for rows.Next() {
		var x model.Series
		if err := rows.Scan(
			&x.ID,
			&x.Title,
			&x.Slug,
			&x.Description,
			&x.CoverImagePath,
			&x.Status,
			&x.CreatedAt,
			&x.UpdatedAt,
		); err != nil {
			return nil, err
		}

		x.Genres = []model.Genre{}
		x.Tags = []model.Tag{}
		out = append(out, x)
	}

	if err := rows.Err(); err != nil {
		return nil, err
	}

	if err := s.attachTaxonomy(ctx, out); err != nil {
		return nil, err
	}

	return out, nil
}

func (s *Store) attachTaxonomy(ctx context.Context, series []model.Series) error {
	if len(series) == 0 {
		return nil
	}

	if err := s.attachGenres(ctx, series); err != nil {
		return err
	}

	return s.attachTags(ctx, series)
}

func (s *Store) attachGenres(ctx context.Context, series []model.Series) error {
	if len(series) == 0 {
		return nil
	}

	ids := make([]string, 0, len(series))
	pos := map[string]int{}

	for i := range series {
		ids = append(ids, series[i].ID)
		pos[series[i].ID] = i
	}

	rows, err := s.db.Query(
		ctx,
		`SELECT
			sg.series_id::text,
			g.id,
			g.name
		FROM series_genres sg
		JOIN genres g ON g.id = sg.genre_id
		WHERE sg.series_id::text = ANY($1::text[])
		ORDER BY g.name`,
		ids,
	)
	if err != nil {
		return err
	}
	defer rows.Close()

	for rows.Next() {
		var sid string
		var genre model.Genre

		if err := rows.Scan(&sid, &genre.ID, &genre.Name); err != nil {
			return err
		}

		if i, ok := pos[sid]; ok {
			series[i].Genres = append(series[i].Genres, genre)
		}
	}

	return rows.Err()
}

func (s *Store) attachTags(ctx context.Context, series []model.Series) error {
	if len(series) == 0 {
		return nil
	}
	ids := make([]string, 0, len(series))
	pos := map[string]int{}
	for i := range series {
		ids = append(ids, series[i].ID)
		pos[series[i].ID] = i
	}
	rows, err := s.db.Query(ctx, `SELECT st.series_id::text,t.id,t.name FROM series_tags st JOIN tags t ON t.id=st.tag_id WHERE st.series_id::text = ANY($1::text[])`, ids)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var sid string
		var t model.Tag
		if err := rows.Scan(&sid, &t.ID, &t.Name); err != nil {
			return err
		}
		if i, ok := pos[sid]; ok {
			series[i].Tags = append(series[i].Tags, t)
		}
	}
	return rows.Err()
}

func (s *Store) SeriesDetail(ctx context.Context, slug string, admin bool, offset, limit int, chapterSearch string) (model.SeriesDetail, error) {
	var d model.SeriesDetail
	err := s.db.QueryRow(ctx, `SELECT id::text,title,slug,description,cover_image_path,status,created_at,updated_at FROM series WHERE slug=$1`, slug).Scan(&d.ID, &d.Title, &d.Slug, &d.Description, &d.CoverImagePath, &d.Status, &d.CreatedAt, &d.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return d, ErrNotFound
	}
	if err != nil {
		return d, err
	}
	d.Series.Genres = []model.Genre{}
	d.Series.Tags = []model.Tag{}
	grows, err := s.db.Query(ctx, `SELECT g.id,g.name FROM genres g JOIN series_genres sg ON sg.genre_id=g.id WHERE sg.series_id=$1::uuid`, d.ID)
	if err != nil {
		return d, err
	}
	d.Genres = []model.Genre{}
	for grows.Next() {
		var g model.Genre
		if err := grows.Scan(&g.ID, &g.Name); err != nil {
			grows.Close()
			return d, err
		}
		d.Genres = append(d.Genres, g)
	}
	grows.Close()
	trows, err := s.db.Query(ctx, `SELECT t.id,t.name FROM tags t JOIN series_tags st ON st.tag_id=t.id WHERE st.series_id=$1::uuid`, d.ID)
	if err != nil {
		return d, err
	}
	d.Tags = []model.Tag{}
	for trows.Next() {
		var t model.Tag
		if err := trows.Scan(&t.ID, &t.Name); err != nil {
			trows.Close()
			return d, err
		}
		d.Tags = append(d.Tags, t)
	}
	trows.Close()
	d.Series.Tags = d.Tags
	chapterWhere := "series_id=$1::uuid"
	if !admin {
		chapterWhere += " AND status='published'"
	}
	args := []any{d.ID, limit + 1, offset}
	if strings.TrimSpace(chapterSearch) != "" {
		chapterWhere += " AND chapter_number::text ILIKE $4"
		args = append(args, "%"+strings.TrimSpace(chapterSearch)+"%")
	}
	q := fmt.Sprintf(`SELECT id::text,series_id::text,chapter_number::float8,title,slug,status,page_count,created_at,updated_at FROM chapters WHERE %s ORDER BY chapter_number DESC,created_at DESC LIMIT $2 OFFSET $3`, chapterWhere)
	rows, err := s.db.Query(ctx, q, args...)
	if err != nil {
		return d, err
	}
	d.Chapters = []model.Chapter{}
	for rows.Next() {
		var c model.Chapter
		if err := rows.Scan(&c.ID, &c.SeriesID, &c.ChapterNumber, &c.Title, &c.Slug, &c.Status, &c.PageCount, &c.CreatedAt, &c.UpdatedAt); err != nil {
			rows.Close()
			return d, err
		}
		d.Chapters = append(d.Chapters, c)
	}
	rows.Close()
	d.ChapterHasMore = len(d.Chapters) > limit
	if d.ChapterHasMore {
		d.Chapters = d.Chapters[:limit]
	}
	d.ChapterOffset = offset
	d.ChapterLimit = limit
	d.ChapterSearch = chapterSearch
	var fc model.FirstChapter
	err = s.db.QueryRow(ctx, `SELECT slug,chapter_number::float8 FROM chapters WHERE series_id=$1::uuid AND status='published' ORDER BY chapter_number ASC LIMIT 1`, d.ID).Scan(&fc.Slug, &fc.ChapterNumber)
	if err == nil {
		d.FirstChapter = &fc
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return d, err
	}
	return d, nil
}

func (s *Store) ChapterDetail(ctx context.Context, seriesSlug, chapterSlug string) (model.ChapterDetail, error) {
	var d model.ChapterDetail
	err := s.db.QueryRow(ctx, `SELECT c.id::text,c.series_id::text,c.chapter_number::float8,c.title,c.slug,c.status,c.page_count,c.created_at,c.updated_at
        FROM chapters c JOIN series s ON s.id=c.series_id WHERE s.slug=$1 AND c.slug=$2 AND c.status='published'`, seriesSlug, chapterSlug).Scan(&d.ID, &d.SeriesID, &d.ChapterNumber, &d.Title, &d.Slug, &d.Status, &d.PageCount, &d.CreatedAt, &d.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		var exists bool
		e := s.db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM series WHERE slug=$1)`, seriesSlug).Scan(&exists)
		if e != nil {
			return d, e
		}
		if !exists {
			return d, fmt.Errorf("series: %w", ErrNotFound)
		}
		return d, fmt.Errorf("chapter: %w", ErrNotFound)
	}
	if err != nil {
		return d, err
	}
	rows, err := s.db.Query(ctx, `SELECT id::text,chapter_id::text,page_number,image_path,width,height FROM pages WHERE chapter_id=$1::uuid ORDER BY page_number`, d.ID)
	if err != nil {
		return d, err
	}
	d.Pages = []model.Page{}
	defer rows.Close()
	for rows.Next() {
		var p model.Page
		if err := rows.Scan(&p.ID, &p.ChapterID, &p.PageNumber, &p.ImagePath, &p.Width, &p.Height); err != nil {
			return d, err
		}
		d.Pages = append(d.Pages, p)
	}
	return d, rows.Err()
}

func (s *Store) Discovery(ctx context.Context) (model.Discovery, error) {
	var out model.Discovery
	popular, err := s.dashboardSeries(ctx, `
		SELECT s.id::text,s.title,s.slug,s.description,s.cover_image_path,s.status,s.created_at,s.updated_at
		FROM series s
		LEFT JOIN bookmarks b ON b.series_id=s.id
		GROUP BY s.id
		ORDER BY COUNT(b.id) DESC,s.created_at DESC
		LIMIT 10`)
	if err != nil {
		return out, err
	}
	recentBase, err := s.dashboardSeries(ctx, `
		SELECT s.id::text,s.title,s.slug,s.description,s.cover_image_path,s.status,s.created_at,s.updated_at
		FROM series s
		JOIN chapters c ON c.series_id=s.id AND c.status='published'
		GROUP BY s.id
		ORDER BY MAX(c.created_at) DESC
		LIMIT 10`)
	if err != nil {
		return out, err
	}
	recent, err := s.enrichLatestChapters(ctx, recentBase, 3)
	if err != nil {
		return out, err
	}
	newest, err := s.dashboardSeries(ctx, `
		SELECT s.id::text,s.title,s.slug,s.description,s.cover_image_path,s.status,s.created_at,s.updated_at
		FROM series s
		ORDER BY s.created_at DESC
		LIMIT 10`)
	if err != nil {
		return out, err
	}
	out.Popular, out.Recent, out.New = popular, recent, newest
	return out, nil
}

func (s *Store) dashboardSeries(ctx context.Context, query string) ([]model.Series, error) {
	rows, err := s.db.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Series, 0)
	for rows.Next() {
		var x model.Series
		if err := rows.Scan(&x.ID, &x.Title, &x.Slug, &x.Description, &x.CoverImagePath, &x.Status, &x.CreatedAt, &x.UpdatedAt); err != nil {
			return nil, err
		}
		x.Genres = []model.Genre{}
		x.Tags = []model.Tag{}
		out = append(out, x)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := s.attachTaxonomy(ctx, out); err != nil {
		return nil, err
	}
	return out, nil
}

func (s *Store) enrichLatestChapters(ctx context.Context, series []model.Series, perSeries int) ([]model.DiscoverySeries, error) {
	out := make([]model.DiscoverySeries, len(series))
	if len(series) == 0 || perSeries <= 0 {
		return out, nil
	}

	ids := make([]string, 0, len(series))
	positions := make(map[string]int, len(series))
	for i := range series {
		ids = append(ids, series[i].ID)
		positions[series[i].ID] = i
		out[i] = model.DiscoverySeries{
			Series:         series[i],
			LatestChapters: []model.LatestChapter{},
		}
	}

	rows, err := s.db.Query(ctx, `
		SELECT ranked.series_id::text,
		       ranked.chapter_number::float8,
		       ranked.title,
		       ranked.slug,
		       ranked.created_at
		FROM (
			SELECT c.series_id,
			       c.chapter_number,
			       c.title,
			       c.slug,
			       c.created_at,
			       ROW_NUMBER() OVER (
				   PARTITION BY c.series_id
				   ORDER BY c.created_at DESC, c.chapter_number DESC
			       ) AS rn
			FROM chapters c
			WHERE c.status='published'
			  AND c.series_id::text = ANY($1::text[])
		) ranked
		WHERE ranked.rn <= $2
		ORDER BY ranked.series_id, ranked.rn`, ids, perSeries)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var seriesID string
		var chapter model.LatestChapter
		if err := rows.Scan(
			&seriesID,
			&chapter.ChapterNumber,
			&chapter.Title,
			&chapter.Slug,
			&chapter.PublishedAt,
		); err != nil {
			return nil, err
		}
		if i, ok := positions[seriesID]; ok {
			out[i].LatestChapters = append(out[i].LatestChapters, chapter)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

func (s *Store) Trending(ctx context.Context, hours int, limit int) ([]model.TrendingSeries, error) {
	rows, err := s.db.Query(ctx, `
        SELECT s.id::text,
               s.title,
               s.slug,
               s.description,
               s.cover_image_path,
               s.status,
               s.created_at,
               s.updated_at,
               SUM(t.open_count)::bigint AS trend_score
        FROM series_trending_hourly t
        JOIN series s ON s.id = t.series_id
        WHERE t.bucket_start >= date_trunc('hour', NOW()) - (($1::int - 1) * INTERVAL '1 hour')
        GROUP BY s.id
        ORDER BY trend_score DESC, MAX(t.bucket_start) DESC, s.updated_at DESC
        LIMIT $2
    `, hours, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]model.TrendingSeries, 0, limit)
	base := make([]model.Series, 0, limit)
	for rows.Next() {
		var item model.TrendingSeries
		if err := rows.Scan(
			&item.ID, &item.Title, &item.Slug, &item.Description, &item.CoverImagePath,
			&item.Status, &item.CreatedAt, &item.UpdatedAt, &item.TrendScore,
		); err != nil {
			return nil, err
		}
		item.Genres = []model.Genre{}
		item.Tags = []model.Tag{}
		out = append(out, item)
		base = append(base, item.Series)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := s.attachTaxonomy(ctx, base); err != nil {
		return nil, err
	}
	for i := range out {
		out[i].Series = base[i]
	}
	return out, nil
}

func (s *Store) PublicCuration(ctx context.Context) (model.CurationResponse, error) {
	var out model.CurationResponse
	picks, err := s.editorPicks(ctx, true)
	if err != nil {
		return out, err
	}
	announcements, err := s.announcements(ctx, true)
	if err != nil {
		return out, err
	}
	out.EditorPicks = picks
	out.Announcements = announcements
	return out, nil
}

func (s *Store) AdminCuration(ctx context.Context) (model.CurationResponse, error) {
	var out model.CurationResponse
	picks, err := s.editorPicks(ctx, false)
	if err != nil {
		return out, err
	}
	announcements, err := s.announcements(ctx, false)
	if err != nil {
		return out, err
	}
	out.EditorPicks = picks
	out.Announcements = announcements
	return out, nil
}

func (s *Store) editorPicks(ctx context.Context, publicOnly bool) ([]model.EditorPick, error) {
	where := ""
	limit := ""
	if publicOnly {
		where = `WHERE ep.is_active = TRUE
		  AND (ep.starts_at IS NULL OR ep.starts_at <= NOW())
		  AND (ep.ends_at IS NULL OR ep.ends_at > NOW())`
		limit = " LIMIT 12"
	}
	rows, err := s.db.Query(ctx, `
		SELECT ep.id::text,
		       s.id::text,s.title,s.slug,s.description,s.cover_image_path,s.status,s.created_at,s.updated_at,
		       ep.label,ep.note,ep.position,ep.is_active,ep.starts_at,ep.ends_at,ep.created_at,ep.updated_at
		FROM editor_picks ep
		JOIN series s ON s.id=ep.series_id
		`+where+`
		ORDER BY ep.position ASC, ep.created_at ASC`+limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.EditorPick, 0)
	base := make([]model.Series, 0)
	for rows.Next() {
		var item model.EditorPick
		if err := rows.Scan(
			&item.ID,
			&item.Series.ID, &item.Series.Title, &item.Series.Slug, &item.Series.Description, &item.Series.CoverImagePath,
			&item.Series.Status, &item.Series.CreatedAt, &item.Series.UpdatedAt,
			&item.Label, &item.Note, &item.Position, &item.IsActive, &item.StartsAt, &item.EndsAt, &item.CreatedAt, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		item.Series.Genres = []model.Genre{}
		item.Series.Tags = []model.Tag{}
		out = append(out, item)
		base = append(base, item.Series)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := s.attachTaxonomy(ctx, base); err != nil {
		return nil, err
	}
	for i := range out {
		out[i].Series = base[i]
	}
	return out, nil
}

func (s *Store) announcements(ctx context.Context, publicOnly bool) ([]model.Announcement, error) {
	where := ""
	limit := ""
	if publicOnly {
		where = `WHERE is_active = TRUE
		  AND (starts_at IS NULL OR starts_at <= NOW())
		  AND (ends_at IS NULL OR ends_at > NOW())`
		limit = " LIMIT 3"
	}
	rows, err := s.db.Query(ctx, `
		SELECT id::text,title,body,link_url,link_label,tone,dismissible,position,is_active,
		       starts_at,ends_at,created_at,updated_at
		FROM announcements
		`+where+`
		ORDER BY position ASC, created_at DESC`+limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]model.Announcement, 0)
	for rows.Next() {
		var item model.Announcement
		if err := rows.Scan(
			&item.ID, &item.Title, &item.Body, &item.LinkURL, &item.LinkLabel, &item.Tone, &item.Dismissible,
			&item.Position, &item.IsActive, &item.StartsAt, &item.EndsAt, &item.CreatedAt, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (s *Store) CreateEditorPick(ctx context.Context, in model.EditorPickUpsertRequest, createdBy string) (model.EditorPick, error) {
	var exists bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM series WHERE id=$1::uuid)`, in.SeriesID).Scan(&exists); err != nil {
		return model.EditorPick{}, err
	}
	if !exists {
		return model.EditorPick{}, ErrNotFound
	}
	var id string
	err := s.db.QueryRow(ctx, `
		INSERT INTO editor_picks(series_id,label,note,position,is_active,starts_at,ends_at,created_by)
		VALUES($1::uuid,$2,$3,$4,$5,$6,$7,NULLIF($8,'')::uuid)
		RETURNING id::text`, in.SeriesID, in.Label, in.Note, in.Position, in.IsActive, in.StartsAt, in.EndsAt, createdBy).Scan(&id)
	if err != nil {
		if isUniqueViolation(err) {
			return model.EditorPick{}, ErrConflict
		}
		return model.EditorPick{}, err
	}
	return s.EditorPickByID(ctx, id)
}

func (s *Store) EditorPickByID(ctx context.Context, id string) (model.EditorPick, error) {
	rows, err := s.db.Query(ctx, `
		SELECT ep.id::text,
		       s.id::text,s.title,s.slug,s.description,s.cover_image_path,s.status,s.created_at,s.updated_at,
		       ep.label,ep.note,ep.position,ep.is_active,ep.starts_at,ep.ends_at,ep.created_at,ep.updated_at
		FROM editor_picks ep JOIN series s ON s.id=ep.series_id
		WHERE ep.id=$1::uuid`, id)
	if err != nil {
		return model.EditorPick{}, err
	}
	defer rows.Close()
	if !rows.Next() {
		return model.EditorPick{}, ErrNotFound
	}
	var item model.EditorPick
	if err := rows.Scan(
		&item.ID,
		&item.Series.ID, &item.Series.Title, &item.Series.Slug, &item.Series.Description, &item.Series.CoverImagePath,
		&item.Series.Status, &item.Series.CreatedAt, &item.Series.UpdatedAt,
		&item.Label, &item.Note, &item.Position, &item.IsActive, &item.StartsAt, &item.EndsAt, &item.CreatedAt, &item.UpdatedAt,
	); err != nil {
		return model.EditorPick{}, err
	}
	base := []model.Series{item.Series}
	if err := s.attachTaxonomy(ctx, base); err != nil {
		return model.EditorPick{}, err
	}
	item.Series = base[0]
	return item, nil
}

func (s *Store) UpdateEditorPick(ctx context.Context, id string, in model.EditorPickUpsertRequest) (model.EditorPick, error) {
	var exists bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM series WHERE id=$1::uuid)`, in.SeriesID).Scan(&exists); err != nil {
		return model.EditorPick{}, err
	}
	if !exists {
		return model.EditorPick{}, ErrNotFound
	}
	cmd, err := s.db.Exec(ctx, `
		UPDATE editor_picks
		SET series_id=$2::uuid,label=$3,note=$4,position=$5,is_active=$6,starts_at=$7,ends_at=$8,updated_at=NOW()
		WHERE id=$1::uuid`, id, in.SeriesID, in.Label, in.Note, in.Position, in.IsActive, in.StartsAt, in.EndsAt)
	if err != nil {
		if isUniqueViolation(err) {
			return model.EditorPick{}, ErrConflict
		}
		return model.EditorPick{}, err
	}
	if cmd.RowsAffected() == 0 {
		return model.EditorPick{}, ErrNotFound
	}
	return s.EditorPickByID(ctx, id)
}

func (s *Store) DeleteEditorPick(ctx context.Context, id string) error {
	cmd, err := s.db.Exec(ctx, `DELETE FROM editor_picks WHERE id=$1::uuid`, id)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (s *Store) CreateAnnouncement(ctx context.Context, in model.AnnouncementUpsertRequest, createdBy string) (model.Announcement, error) {
	var id string
	err := s.db.QueryRow(ctx, `
		INSERT INTO announcements(title,body,link_url,link_label,tone,dismissible,position,is_active,starts_at,ends_at,created_by)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NULLIF($11,'')::uuid)
		RETURNING id::text`, in.Title, in.Body, in.LinkURL, in.LinkLabel, in.Tone, in.Dismissible, in.Position, in.IsActive, in.StartsAt, in.EndsAt, createdBy).Scan(&id)
	if err != nil {
		return model.Announcement{}, err
	}
	return s.AnnouncementByID(ctx, id)
}

func (s *Store) AnnouncementByID(ctx context.Context, id string) (model.Announcement, error) {
	var item model.Announcement
	err := s.db.QueryRow(ctx, `
		SELECT id::text,title,body,link_url,link_label,tone,dismissible,position,is_active,
		       starts_at,ends_at,created_at,updated_at
		FROM announcements WHERE id=$1::uuid`, id).Scan(
		&item.ID, &item.Title, &item.Body, &item.LinkURL, &item.LinkLabel, &item.Tone, &item.Dismissible,
		&item.Position, &item.IsActive, &item.StartsAt, &item.EndsAt, &item.CreatedAt, &item.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Announcement{}, ErrNotFound
	}
	return item, err
}

func (s *Store) UpdateAnnouncement(ctx context.Context, id string, in model.AnnouncementUpsertRequest) (model.Announcement, error) {
	cmd, err := s.db.Exec(ctx, `
		UPDATE announcements
		SET title=$2,body=$3,link_url=$4,link_label=$5,tone=$6,dismissible=$7,position=$8,is_active=$9,
		    starts_at=$10,ends_at=$11,updated_at=NOW()
		WHERE id=$1::uuid`, id, in.Title, in.Body, in.LinkURL, in.LinkLabel, in.Tone, in.Dismissible, in.Position, in.IsActive, in.StartsAt, in.EndsAt)
	if err != nil {
		return model.Announcement{}, err
	}
	if cmd.RowsAffected() == 0 {
		return model.Announcement{}, ErrNotFound
	}
	return s.AnnouncementByID(ctx, id)
}

func (s *Store) DeleteAnnouncement(ctx context.Context, id string) error {
	cmd, err := s.db.Exec(ctx, `DELETE FROM announcements WHERE id=$1::uuid`, id)
	if err != nil {
		return err
	}
	if cmd.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

func (s *Store) AdminStats(ctx context.Context) (model.AdminStats, error) {
	var out model.AdminStats
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM series`).Scan(&out.SeriesCount); err != nil {
		return out, err
	}
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM chapters`).Scan(&out.ChapterCount); err != nil {
		return out, err
	}
	return out, nil
}

func (s *Store) CreateSeries(ctx context.Context, in model.SeriesCreateRequest) (model.Series, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.Series{}, err
	}
	defer tx.Rollback(ctx)

	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM series WHERE slug=$1)`, in.Slug).Scan(&exists); err != nil {
		return model.Series{}, err
	}
	if exists {
		return model.Series{}, ErrConflict
	}

	var out model.Series
	err = tx.QueryRow(ctx, `
		INSERT INTO series(title,slug,description,cover_image_path,status)
		VALUES($1,$2,$3,$4,$5)
		RETURNING id::text,title,slug,description,cover_image_path,status,created_at,updated_at`,
		in.Title, in.Slug, in.Description, in.CoverImagePath, in.Status,
	).Scan(&out.ID, &out.Title, &out.Slug, &out.Description, &out.CoverImagePath, &out.Status, &out.CreatedAt, &out.UpdatedAt)
	if err != nil {
		if isUniqueViolation(err) {
			return model.Series{}, ErrConflict
		}
		return model.Series{}, err
	}

	genreIDs := in.GenreIDs
	if len(in.GenreNames) > 0 {
		genreIDs, err = getOrCreateTaxonomyIDsTx(ctx, tx, "genres", normalizeTaxonomyNames(in.GenreNames))
		if err != nil {
			return model.Series{}, err
		}
	}
	if err := setSeriesGenresTx(ctx, tx, out.ID, genreIDs); err != nil {
		return model.Series{}, err
	}
	tagIDs, err := getOrCreateTaxonomyIDsTx(ctx, tx, "tags", normalizeTaxonomyNames(in.TagNames))
	if err != nil {
		return model.Series{}, err
	}
	if err := setSeriesTagsTx(ctx, tx, out.ID, tagIDs); err != nil {
		return model.Series{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.Series{}, err
	}
	items := []model.Series{out}
	if err := s.attachTaxonomy(ctx, items); err != nil {
		return model.Series{}, err
	}
	return items[0], nil
}

func (s *Store) SetSeriesCover(ctx context.Context, seriesID string, coverPath *string, mediaGeneration int64, metadata ...EventMetadata) (model.Series, error) {
	if coverPath != nil && mediaGeneration < 1 {
		return model.Series{}, ErrConflict
	}
	if coverPath == nil {
		mediaGeneration = 0
	}
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.Series{}, err
	}
	defer tx.Rollback(ctx)

	var current model.Series
	var oldCoverGeneration int64
	err = tx.QueryRow(ctx, `
		SELECT id::text,title,slug,description,cover_image_path,cover_media_generation,status,created_at,updated_at
		FROM series
		WHERE id=$1::uuid
		FOR UPDATE`, seriesID,
	).Scan(
		&current.ID, &current.Title, &current.Slug, &current.Description,
		&current.CoverImagePath, &oldCoverGeneration, &current.Status, &current.CreatedAt, &current.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Series{}, ErrNotFound
	}
	if err != nil {
		return model.Series{}, err
	}

	oldCoverPath := current.CoverImagePath
	unchanged := oldCoverPath == nil && coverPath == nil
	if oldCoverPath != nil && coverPath != nil && *oldCoverPath == *coverPath && oldCoverGeneration == mediaGeneration {
		unchanged = true
	}
	if unchanged {
		if err := tx.Commit(ctx); err != nil {
			return model.Series{}, err
		}
		items := []model.Series{current}
		if err := s.attachTaxonomy(ctx, items); err != nil {
			return model.Series{}, err
		}
		return items[0], nil
	}

	err = tx.QueryRow(ctx, `
		UPDATE series
		SET cover_image_path=$2, cover_media_generation=$3, updated_at=NOW()
		WHERE id=$1::uuid
		RETURNING id::text,title,slug,description,cover_image_path,status,created_at,updated_at`,
		seriesID, coverPath, mediaGeneration,
	).Scan(
		&current.ID, &current.Title, &current.Slug, &current.Description,
		&current.CoverImagePath, &current.Status, &current.CreatedAt, &current.UpdatedAt,
	)
	if err != nil {
		return model.Series{}, err
	}

	if oldCoverPath != nil && (coverPath == nil || *oldCoverPath != *coverPath) {
		objectRefs := []cleanupObjectRef{{Path: *oldCoverPath, Generation: oldCoverGeneration, Kind: "cover"}}
		payload := map[string]any{
			"schema_version": 2,
			"series_id":      seriesID,
			"series_slug":    current.Slug,
			"object_refs":    objectRefs,
			"image_paths":    cleanupObjectPaths(objectRefs),
			"reason":         "catalog-cover-replacement",
		}
		if err := enqueueCleanupTx(ctx, tx, "series_cover", seriesID, payload); err != nil {
			return model.Series{}, err
		}
	}

	eventMetadata := EventMetadata{}
	if len(metadata) > 0 {
		eventMetadata = metadata[0]
	}
	if _, err := enqueueSeriesUpdatedTx(
		ctx,
		tx,
		seriesID,
		current.Slug,
		[]string{"cover_image_path"},
		current.UpdatedAt,
		"catalog-cover-update",
		eventMetadata,
	); err != nil {
		return model.Series{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.Series{}, err
	}
	items := []model.Series{current}
	if err := s.attachTaxonomy(ctx, items); err != nil {
		return model.Series{}, err
	}
	return items[0], nil
}

func (s *Store) UpdateSeries(ctx context.Context, seriesID string, in model.SeriesUpdateRequest, metadata ...EventMetadata) (model.Series, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.Series{}, err
	}
	defer tx.Rollback(ctx)

	var current model.Series
	var oldCoverGeneration int64
	err = tx.QueryRow(ctx, `SELECT id::text,title,slug,description,cover_image_path,cover_media_generation,status,created_at,updated_at FROM series WHERE id=$1::uuid FOR UPDATE`, seriesID).
		Scan(&current.ID, &current.Title, &current.Slug, &current.Description, &current.CoverImagePath, &oldCoverGeneration, &current.Status, &current.CreatedAt, &current.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Series{}, ErrNotFound
	}
	if err != nil {
		return model.Series{}, err
	}

	oldCoverPath := current.CoverImagePath
	coverGeneration := oldCoverGeneration
	changedFields := make([]string, 0, 6)

	if in.Title != nil && current.Title != *in.Title {
		current.Title = *in.Title
		changedFields = append(changedFields, "title")
	}
	if in.Description != nil {
		if current.Description == nil || *current.Description != *in.Description {
			current.Description = in.Description
			changedFields = append(changedFields, "description")
		}
	}
	if in.CoverImagePath != nil {
		if current.CoverImagePath == nil || *current.CoverImagePath != *in.CoverImagePath {
			current.CoverImagePath = in.CoverImagePath
			// Generic admin metadata updates do not carry verified Media
			// completion evidence. Keep the path for compatibility but mark
			// its generation as legacy/unknown. Media-owned cover attachment
			// uses SetSeriesCover and records the claimed generation.
			coverGeneration = 0
			changedFields = append(changedFields, "cover_image_path")
		}
	}
	if in.Status != nil && current.Status != *in.Status {
		current.Status = *in.Status
		changedFields = append(changedFields, "status")
	}

	genresChanged := false
	if in.GenreIDs != nil {
		currentGenreIDs, err := seriesTaxonomyIDsTx(ctx, tx, "series_genres", "genre_id", seriesID)
		if err != nil {
			return model.Series{}, err
		}
		genresChanged = !equalIntSet(currentGenreIDs, in.GenreIDs)
		if genresChanged {
			changedFields = append(changedFields, "genres")
		}
	}

	tagsChanged := false
	var requestedTagIDs []int
	tagUpdateRequested := in.TagIDs != nil || in.TagNames != nil
	if in.TagNames != nil {
		requestedTagIDs, err = getOrCreateTaxonomyIDsTx(ctx, tx, "tags", normalizeTaxonomyNames(*in.TagNames))
		if err != nil {
			return model.Series{}, err
		}
	} else if in.TagIDs != nil {
		requestedTagIDs = in.TagIDs
	}
	if tagUpdateRequested {
		currentTagIDs, err := seriesTaxonomyIDsTx(ctx, tx, "series_tags", "tag_id", seriesID)
		if err != nil {
			return model.Series{}, err
		}
		tagsChanged = !equalIntSet(currentTagIDs, requestedTagIDs)
		if tagsChanged {
			changedFields = append(changedFields, "tags")
		}
	}

	if len(changedFields) == 0 {
		if err := tx.Commit(ctx); err != nil {
			return model.Series{}, err
		}
		items := []model.Series{current}
		if err := s.attachTaxonomy(ctx, items); err != nil {
			return model.Series{}, err
		}
		return items[0], nil
	}

	err = tx.QueryRow(ctx, `
		UPDATE series
		SET title=$2,description=$3,cover_image_path=$4,cover_media_generation=$5,status=$6::varchar(20),updated_at=NOW()
		WHERE id=$1::uuid
		RETURNING id::text,title,slug,description,cover_image_path,status,created_at,updated_at`,
		seriesID, current.Title, current.Description, current.CoverImagePath, coverGeneration, current.Status,
	).Scan(&current.ID, &current.Title, &current.Slug, &current.Description, &current.CoverImagePath, &current.Status, &current.CreatedAt, &current.UpdatedAt)
	if err != nil {
		return model.Series{}, err
	}

	if genresChanged {
		if err := setSeriesGenresTx(ctx, tx, seriesID, in.GenreIDs); err != nil {
			return model.Series{}, err
		}
	}
	if tagsChanged {
		if err := setSeriesTagsTx(ctx, tx, seriesID, requestedTagIDs); err != nil {
			return model.Series{}, err
		}
	}

	coverChanged := false
	if in.CoverImagePath != nil {
		if oldCoverPath == nil {
			coverChanged = true
		} else {
			coverChanged = *oldCoverPath != *in.CoverImagePath
		}
	}
	if coverChanged && oldCoverPath != nil {
		objectRefs := []cleanupObjectRef{{
			Path:       *oldCoverPath,
			Generation: oldCoverGeneration,
			Kind:       "cover",
		}}
		payload := map[string]any{
			"schema_version": 2,
			"series_id":      seriesID,
			"series_slug":    current.Slug,
			"object_refs":    objectRefs,
			"image_paths":    cleanupObjectPaths(objectRefs),
			"reason":         "catalog-admin-cover-replacement",
		}
		if err := enqueueCleanupTx(ctx, tx, "series_cover", seriesID, payload); err != nil {
			return model.Series{}, err
		}
	}

	eventMetadata := EventMetadata{}
	if len(metadata) > 0 {
		eventMetadata = metadata[0]
	}
	if _, err := enqueueSeriesUpdatedTx(
		ctx,
		tx,
		seriesID,
		current.Slug,
		changedFields,
		current.UpdatedAt,
		"catalog-admin-update",
		eventMetadata,
	); err != nil {
		return model.Series{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.Series{}, err
	}
	items := []model.Series{current}
	if err := s.attachTaxonomy(ctx, items); err != nil {
		return model.Series{}, err
	}
	return items[0], nil
}

func (s *Store) DeleteSeries(ctx context.Context, seriesID string) (string, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)

	var seriesSlug string
	var coverPath *string
	var coverMediaGeneration int64
	err = tx.QueryRow(ctx, `SELECT slug, cover_image_path, cover_media_generation FROM series WHERE id=$1::uuid FOR UPDATE`, seriesID).Scan(&seriesSlug, &coverPath, &coverMediaGeneration)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", err
	}

	chapterIDs := []string{}
	rows, err := tx.Query(ctx, `SELECT id::text FROM chapters WHERE series_id=$1::uuid`, seriesID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", err
		}
		chapterIDs = append(chapterIDs, id)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	objectRefs := []cleanupObjectRef{}
	if coverPath != nil {
		objectRefs = append(objectRefs, cleanupObjectRef{Path: *coverPath, Generation: coverMediaGeneration, Kind: "cover"})
	}
	rows, err = tx.Query(ctx, `
		SELECT p.image_path, p.responsive_image_path, p.media_generation
		FROM pages p JOIN chapters c ON c.id=p.chapter_id
		WHERE c.series_id=$1::uuid
	`, seriesID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var path string
		var responsivePath *string
		var mediaGeneration int64
		if err := rows.Scan(&path, &responsivePath, &mediaGeneration); err != nil {
			rows.Close()
			return "", err
		}
		objectRefs = appendCleanupObjectRef(objectRefs, path, mediaGeneration, "page-primary")
		if responsivePath != nil && *responsivePath != "" {
			objectRefs = appendCleanupObjectRef(objectRefs, *responsivePath, mediaGeneration, "page-responsive")
		}
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	localStagingPrefixes := []string{}
	rows, err = tx.Query(ctx, `SELECT id::text FROM scraper_series_drafts WHERE published_series_id=$1::uuid`, seriesID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/series-drafts/"+id)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	rows, err = tx.Query(ctx, `SELECT id::text FROM scraper_drafts WHERE target_series_id=$1::uuid`, seriesID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/staging/"+id)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	rows, err = tx.Query(ctx, `SELECT id::text FROM scraper_batch_uploads WHERE target_series_id=$1::uuid`, seriesID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/batches/"+id)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	payload := map[string]any{
		"schema_version":         2,
		"series_id":              seriesID,
		"series_slug":            seriesSlug,
		"chapter_ids":            chapterIDs,
		"object_refs":            objectRefs,
		"image_paths":            cleanupObjectPaths(objectRefs),
		"local_staging_prefixes": localStagingPrefixes,
		"reason":                 "catalog-series-delete",
	}
	cleanupJobID, err := enqueueCleanupTxWithID(ctx, tx, "series", seriesID, payload)
	if err != nil {
		return "", err
	}
	cmd, err := tx.Exec(ctx, `DELETE FROM series WHERE id=$1::uuid`, seriesID)
	if err != nil {
		return "", err
	}
	if cmd.RowsAffected() == 0 {
		return "", ErrNotFound
	}
	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	return cleanupJobID, nil
}

func setSeriesGenresTx(ctx context.Context, tx pgx.Tx, seriesID string, genreIDs []int) error {
	if _, err := tx.Exec(ctx, `DELETE FROM series_genres WHERE series_id=$1::uuid`, seriesID); err != nil {
		return err
	}
	for _, id := range genreIDs {
		if _, err := tx.Exec(ctx, `INSERT INTO series_genres(series_id,genre_id) VALUES($1::uuid,$2)`, seriesID, id); err != nil {
			if isForeignKeyViolation(err) {
				return ErrInvalidReference
			}
			return err
		}
	}
	return nil
}

func setSeriesTagsTx(ctx context.Context, tx pgx.Tx, seriesID string, tagIDs []int) error {
	if _, err := tx.Exec(ctx, `DELETE FROM series_tags WHERE series_id=$1::uuid`, seriesID); err != nil {
		return err
	}
	for _, id := range tagIDs {
		if _, err := tx.Exec(ctx, `INSERT INTO series_tags(series_id,tag_id) VALUES($1::uuid,$2)`, seriesID, id); err != nil {
			if isForeignKeyViolation(err) {
				return ErrInvalidReference
			}
			return err
		}
	}
	return nil
}

func normalizeTaxonomyNames(names []string) []string {
	out := make([]string, 0, len(names))
	for _, raw := range names {
		name := strings.TrimSpace(raw)
		if name == "" {
			continue
		}
		duplicate := false
		for _, existing := range out {
			if strings.EqualFold(existing, name) {
				duplicate = true
				break
			}
		}
		if !duplicate {
			out = append(out, name)
		}
	}
	return out
}

func getOrCreateTaxonomyIDsTx(ctx context.Context, tx pgx.Tx, table string, names []string) ([]int, error) {
	var selectSQL, insertSQL string
	switch table {
	case "genres":
		selectSQL = `SELECT id FROM genres WHERE upper(name)=upper($1) LIMIT 1`
		insertSQL = `INSERT INTO genres(name) VALUES($1) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id`
	case "tags":
		selectSQL = `SELECT id FROM tags WHERE upper(name)=upper($1) LIMIT 1`
		insertSQL = `INSERT INTO tags(name) VALUES($1) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id`
	default:
		return nil, errors.New("unsupported taxonomy table")
	}

	ids := make([]int, 0, len(names))
	for _, name := range names {
		var id int
		err := tx.QueryRow(ctx, selectSQL, name).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			err = tx.QueryRow(ctx, insertSQL, name).Scan(&id)
		}
		if err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, nil
}

func isUniqueViolation(err error) bool {
	type sqlState interface{ SQLState() string }
	var state sqlState
	return errors.As(err, &state) && state.SQLState() == "23505"
}

func isForeignKeyViolation(err error) bool {
	type sqlState interface{ SQLState() string }
	var state sqlState
	return errors.As(err, &state) && state.SQLState() == "23503"
}

func (s *Store) CreateChapter(ctx context.Context, seriesID string, in model.ChapterCreateRequest) (model.Chapter, error) {
	if in.Status == "published" {
		return model.Chapter{}, ErrNoPages
	}
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.Chapter{}, err
	}
	defer tx.Rollback(ctx)

	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM series WHERE id=$1::uuid)`, seriesID).Scan(&exists); err != nil {
		return model.Chapter{}, err
	}
	if !exists {
		return model.Chapter{}, ErrNotFound
	}

	var out model.Chapter
	err = tx.QueryRow(ctx, `
		INSERT INTO chapters(series_id,chapter_number,title,slug,status,page_count)
		VALUES($1::uuid,$2,$3,$4,$5,0)
		RETURNING id::text,series_id::text,chapter_number::float8,title,slug,status,page_count,created_at,updated_at`,
		seriesID, in.ChapterNumber, in.Title, in.Slug, in.Status,
	).Scan(&out.ID, &out.SeriesID, &out.ChapterNumber, &out.Title, &out.Slug, &out.Status, &out.PageCount, &out.CreatedAt, &out.UpdatedAt)
	if err != nil {
		if isUniqueViolation(err) {
			return model.Chapter{}, ErrConflict
		}
		return model.Chapter{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.Chapter{}, err
	}
	return out, nil
}

func (s *Store) UpdateChapter(ctx context.Context, seriesID, chapterID string, in model.ChapterUpdateRequest) (model.Chapter, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return model.Chapter{}, err
	}
	defer tx.Rollback(ctx)

	var current model.Chapter
	err = tx.QueryRow(ctx, `
		SELECT id::text,series_id::text,chapter_number::float8,title,slug,status,page_count,created_at,updated_at
		FROM chapters WHERE id=$1::uuid AND series_id=$2::uuid FOR UPDATE`, chapterID, seriesID,
	).Scan(&current.ID, &current.SeriesID, &current.ChapterNumber, &current.Title, &current.Slug, &current.Status, &current.PageCount, &current.CreatedAt, &current.UpdatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return model.Chapter{}, ErrNotFound
	}
	if err != nil {
		return model.Chapter{}, err
	}

	wasPublished := current.Status == "published"
	if !wasPublished && in.Status != nil && *in.Status == "published" {
		return model.Chapter{}, ErrPublicationRequiresMedia
	}
	if in.ChapterNumber != nil {
		current.ChapterNumber = *in.ChapterNumber
	}
	if in.Title != nil {
		current.Title = in.Title
	}
	if in.Slug != nil {
		current.Slug = *in.Slug
	}
	if in.Status != nil {
		current.Status = *in.Status
	}
	err = tx.QueryRow(ctx, `
		UPDATE chapters
		SET chapter_number=$3,title=$4,slug=$5,status=$6::varchar(20),updated_at=NOW()
		WHERE id=$1::uuid AND series_id=$2::uuid
		RETURNING id::text,series_id::text,chapter_number::float8,title,slug,status,page_count,created_at,updated_at`,
		chapterID, seriesID, current.ChapterNumber, current.Title, current.Slug, current.Status,
	).Scan(&current.ID, &current.SeriesID, &current.ChapterNumber, &current.Title, &current.Slug, &current.Status, &current.PageCount, &current.CreatedAt, &current.UpdatedAt)
	if err != nil {
		if isUniqueViolation(err) {
			return model.Chapter{}, ErrConflict
		}
		return model.Chapter{}, err
	}

	if err := tx.Commit(ctx); err != nil {
		return model.Chapter{}, err
	}
	return current, nil
}

func (s *Store) DeleteChapter(ctx context.Context, seriesID, chapterID string) (string, error) {
	tx, err := s.db.Begin(ctx)
	if err != nil {
		return "", err
	}
	defer tx.Rollback(ctx)

	var seriesSlug, chapterSlug string
	err = tx.QueryRow(ctx, `
		SELECT s.slug, c.slug
		FROM chapters c JOIN series s ON s.id=c.series_id
		WHERE c.id=$1::uuid AND c.series_id=$2::uuid
		FOR UPDATE
	`, chapterID, seriesID).Scan(&seriesSlug, &chapterSlug)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", err
	}

	objectRefs := []cleanupObjectRef{}
	rows, err := tx.Query(ctx, `SELECT image_path, responsive_image_path, media_generation FROM pages WHERE chapter_id=$1::uuid`, chapterID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var path string
		var responsivePath *string
		var mediaGeneration int64
		if err := rows.Scan(&path, &responsivePath, &mediaGeneration); err != nil {
			rows.Close()
			return "", err
		}
		objectRefs = appendCleanupObjectRef(objectRefs, path, mediaGeneration, "page-primary")
		if responsivePath != nil && *responsivePath != "" {
			objectRefs = appendCleanupObjectRef(objectRefs, *responsivePath, mediaGeneration, "page-responsive")
		}
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	localStagingPrefixes := []string{}
	rows, err = tx.Query(ctx, `SELECT id::text FROM scraper_drafts WHERE published_chapter_id=$1::uuid`, chapterID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/staging/"+id)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	rows, err = tx.Query(ctx, `
		SELECT batch_id::text, chapter_slug
		FROM scraper_batch_items
		WHERE existing_chapter_id=$1::uuid OR published_chapter_id=$1::uuid
	`, chapterID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var batchID, slug string
		if err := rows.Scan(&batchID, &slug); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/batches/"+batchID+"/"+slug)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	rows, err = tx.Query(ctx, `
		SELECT id::text, draft_id::text
		FROM scraper_series_draft_chapters
		WHERE published_chapter_id=$1::uuid
	`, chapterID)
	if err != nil {
		return "", err
	}
	for rows.Next() {
		var draftChapterID, draftID string
		if err := rows.Scan(&draftChapterID, &draftID); err != nil {
			rows.Close()
			return "", err
		}
		localStagingPrefixes = appendUniqueString(localStagingPrefixes, "_scraper/series-drafts/"+draftID+"/chapters/"+draftChapterID)
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return "", err
	}
	rows.Close()

	payload := map[string]any{
		"schema_version":         2,
		"series_id":              seriesID,
		"series_slug":            seriesSlug,
		"chapter_ids":            []string{chapterID},
		"chapter_slug":           chapterSlug,
		"object_refs":            objectRefs,
		"image_paths":            cleanupObjectPaths(objectRefs),
		"local_staging_prefixes": localStagingPrefixes,
		"reason":                 "catalog-chapter-delete",
	}
	cleanupJobID, err := enqueueCleanupTxWithID(ctx, tx, "chapter", chapterID, payload)
	if err != nil {
		return "", err
	}
	cmd, err := tx.Exec(ctx, `DELETE FROM chapters WHERE id=$1::uuid AND series_id=$2::uuid`, chapterID, seriesID)
	if err != nil {
		return "", err
	}
	if cmd.RowsAffected() == 0 {
		return "", ErrNotFound
	}
	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	return cleanupJobID, nil
}
