package model

import "time"

type Genre struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
}
type Tag struct {
	ID   int    `json:"id"`
	Name string `json:"name"`
}

type LatestChapter struct {
	ChapterNumber float64   `json:"chapter_number"`
	Title         *string   `json:"title"`
	Slug          string    `json:"slug"`
	PublishedAt   time.Time `json:"published_at"`
}

type Series struct {
	ID             string    `json:"id"`
	Title          string    `json:"title"`
	Slug           string    `json:"slug"`
	Description    *string   `json:"description"`
	CoverImagePath *string   `json:"cover_image_path"`
	Status         string    `json:"status"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
	Genres         []Genre   `json:"genres"`
	Tags           []Tag     `json:"tags"`
}

type Chapter struct {
	ID            string    `json:"id"`
	SeriesID      string    `json:"series_id"`
	ChapterNumber float64   `json:"chapter_number"`
	Title         *string   `json:"title"`
	Slug          string    `json:"slug"`
	Status        string    `json:"status"`
	PageCount     int       `json:"page_count"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type Page struct {
	ID         string `json:"id"`
	ChapterID  string `json:"chapter_id"`
	PageNumber int    `json:"page_number"`
	ImagePath  string `json:"image_path"`
	Width      *int   `json:"width"`
	Height     *int   `json:"height"`
}

type ChapterDetail struct {
	Chapter
	Pages []Page `json:"pages"`
}

type FirstChapter struct {
	Slug          string  `json:"slug"`
	ChapterNumber float64 `json:"chapter_number"`
}

type SeriesDetail struct {
	Series
	Chapters       []Chapter     `json:"chapters"`
	ChapterOffset  int           `json:"chapter_offset"`
	ChapterLimit   int           `json:"chapter_limit"`
	ChapterHasMore bool          `json:"chapter_has_more"`
	ChapterSearch  string        `json:"chapter_search,omitempty"`
	FirstChapter   *FirstChapter `json:"first_chapter"`
}

type DiscoverySeries struct {
	Series
	LatestChapters []LatestChapter `json:"latest_chapters"`
}

type Discovery struct {
	Popular []Series          `json:"popular"`
	Recent  []DiscoverySeries `json:"recent"`
	New     []Series          `json:"new"`
}

type TrendingSeries struct {
	Series
	TrendScore int64 `json:"trend_score"`
}

type TrendingResponse struct {
	Window      string           `json:"window"`
	GeneratedAt time.Time        `json:"generated_at"`
	Items       []TrendingSeries `json:"items"`
}

type EditorPick struct {
	ID        string     `json:"id"`
	Series    Series     `json:"series"`
	Label     *string    `json:"label"`
	Note      *string    `json:"note"`
	Position  int        `json:"position"`
	IsActive  bool       `json:"is_active"`
	StartsAt  *time.Time `json:"starts_at"`
	EndsAt    *time.Time `json:"ends_at"`
	CreatedAt time.Time  `json:"created_at"`
	UpdatedAt time.Time  `json:"updated_at"`
}

type Announcement struct {
	ID          string     `json:"id"`
	Title       string     `json:"title"`
	Body        string     `json:"body"`
	LinkURL     *string    `json:"link_url"`
	LinkLabel   *string    `json:"link_label"`
	Tone        string     `json:"tone"`
	Dismissible bool       `json:"dismissible"`
	Position    int        `json:"position"`
	IsActive    bool       `json:"is_active"`
	StartsAt    *time.Time `json:"starts_at"`
	EndsAt      *time.Time `json:"ends_at"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

type CurationResponse struct {
	EditorPicks   []EditorPick   `json:"editor_picks"`
	Announcements []Announcement `json:"announcements"`
}

type EditorPickUpsertRequest struct {
	SeriesID string     `json:"series_id"`
	Label    *string    `json:"label"`
	Note     *string    `json:"note"`
	Position int        `json:"position"`
	IsActive bool       `json:"is_active"`
	StartsAt *time.Time `json:"starts_at"`
	EndsAt   *time.Time `json:"ends_at"`
}

type AnnouncementUpsertRequest struct {
	Title       string     `json:"title"`
	Body        string     `json:"body"`
	LinkURL     *string    `json:"link_url"`
	LinkLabel   *string    `json:"link_label"`
	Tone        string     `json:"tone"`
	Dismissible bool       `json:"dismissible"`
	Position    int        `json:"position"`
	IsActive    bool       `json:"is_active"`
	StartsAt    *time.Time `json:"starts_at"`
	EndsAt      *time.Time `json:"ends_at"`
}

type AdminStats struct {
	SeriesCount  int64 `json:"series_count"`
	ChapterCount int64 `json:"chapter_count"`
}

type SeriesCreateRequest struct {
	Title          string   `json:"title"`
	Slug           string   `json:"slug"`
	Description    *string  `json:"description"`
	CoverImagePath *string  `json:"cover_image_path"`
	Status         string   `json:"status"`
	GenreIDs       []int    `json:"genre_ids"`
	GenreNames     []string `json:"genre_names"`
	TagNames       []string `json:"tag_names"`
}

type SeriesUpdateRequest struct {
	Title          *string   `json:"title"`
	Description    *string   `json:"description"`
	CoverImagePath *string   `json:"cover_image_path"`
	Status         *string   `json:"status"`
	GenreIDs       []int     `json:"genre_ids"`
	TagIDs         []int     `json:"tag_ids"`
	TagNames       *[]string `json:"tag_names"`
}

type ChapterCreateRequest struct {
	ChapterNumber float64 `json:"chapter_number"`
	Title         *string `json:"title"`
	Slug          string  `json:"slug"`
	Status        string  `json:"status"`
}

type ChapterUpdateRequest struct {
	ChapterNumber *float64 `json:"chapter_number"`
	Title         *string  `json:"title"`
	Slug          *string  `json:"slug"`
	Status        *string  `json:"status"`
}
