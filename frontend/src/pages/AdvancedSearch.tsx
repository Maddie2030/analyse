import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  ChevronDown,
  ChevronUp,
  Search,
  SlidersHorizontal,
  Star,
  Bookmark,
  Users,
  X,
} from 'lucide-react';
import {
  api,
  type Genre,
  type Series,
  type SeriesSocialMetrics,
  type Tag,
} from '../api/client';

const LIMIT = 20;

const STATUSES = [
  { value: '', label: 'Any status' },
  { value: 'ongoing', label: 'Ongoing' },
  { value: 'completed', label: 'Completed' },
  { value: 'hiatus', label: 'Hiatus' },
];

const RATING_THRESHOLDS = [
  { value: '', label: 'Any rating' },
  { value: '4.5', label: '4.5+ stars' },
  { value: '4.0', label: '4.0+ stars' },
  { value: '3.5', label: '3.5+ stars' },
  { value: '3.0', label: '3.0+ stars' },
  { value: '2.5', label: '2.5+ stars' },
];


const SORT_OPTIONS = [
  { value: 'relevance', label: 'Best match' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'newest', label: 'Newest series' },
  { value: 'rating', label: 'Highest rated' },
  { value: 'popular', label: 'Most bookmarked' },
  { value: 'title', label: 'Title A–Z' },
];

function parseIds(value: string | null): number[] {
  if (!value) return [];

  return Array.from(
    new Set(
      value
        .split(',')
        .map((item) => Number(item))
        .filter((item) => Number.isInteger(item) && item > 0)
    )
  );
}

export default function AdvancedSearch() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [taxonomyLoading, setTaxonomyLoading] = useState(true);

  const [search, setSearch] = useState(searchParams.get('search') ?? '');
  const [selectedGenreIds, setSelectedGenreIds] = useState<number[]>(
    parseIds(searchParams.get('genre'))
  );
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>(
    parseIds(searchParams.get('tag'))
  );
  const [status, setStatus] = useState(searchParams.get('status') ?? '');
  const [minRating, setMinRating] = useState(searchParams.get('min_rating') ?? '');
  const [sort, setSort] = useState(searchParams.get('sort') ?? 'relevance');

  const [series, setSeries] = useState<Series[]>([]);
  const [socialMetrics, setSocialMetrics] = useState<Record<string, SeriesSocialMetrics>>({});
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);

  const [genresOpen, setGenresOpen] = useState(true);
  const [tagsOpen, setTagsOpen] = useState(true);
  const [statusOpen, setStatusOpen] = useState(true);
  const [ratingOpen, setRatingOpen] = useState(true);

  const [genreQuery, setGenreQuery] = useState('');
  const [tagQuery, setTagQuery] = useState('');
  const [error, setError] = useState('');
  const searchRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const loadTaxonomy = async () => {
      setTaxonomyLoading(true);

      try {
        const [genreRows, tagRows] = await Promise.all([
          api.getGenres(),
          api.getTags(),
        ]);

        if (!cancelled) {
          setGenres(genreRows);
          setTags(tagRows);

          const validGenreIds = new Set(
            genreRows.map((genre) => genre.id)
          );
          const validTagIds = new Set(
            tagRows.map((tag) => tag.id)
          );

          setSelectedGenreIds((current) =>
            current.filter((id) => validGenreIds.has(id))
          );
          setSelectedTagIds((current) =>
            current.filter((id) => validTagIds.has(id))
          );
        }
      } catch {
        if (!cancelled) {
          setError('Unable to load genres/tags from the catalog.');
        }
      } finally {
        if (!cancelled) {
          setTaxonomyLoading(false);
        }
      }
    };

    void loadTaxonomy();

    return () => {
      cancelled = true;
    };
  }, []);

  const runSearch = useCallback(
    async (pageOffset: number) => {
      const requestId = ++searchRequestRef.current;
      setLoading(true);
      setError('');

      const params = new URLSearchParams();

      if (search.trim()) params.set('search', search.trim());
      if (status) params.set('status', status);
      if (minRating) params.set('min_rating', minRating);
      if (sort) params.set('sort', sort);

      if (selectedGenreIds.length) {
        params.set('genre', selectedGenreIds.join(','));
      }

      if (selectedTagIds.length) {
        params.set('tag', selectedTagIds.join(','));
      }

      params.set('offset', String(pageOffset));
      params.set('limit', String(LIMIT));

      try {
        const data = await api.listSeries(`?${params.toString()}`);
        if (requestId !== searchRequestRef.current) return;
        setSeries(data);
        setHasSearched(true);

        if (data.length > 0) {
          try {
            const metrics = await api.seriesSocialMetricsBatch(
              data.map((item) => item.id)
            );
            if (requestId !== searchRequestRef.current) return;
            setSocialMetrics(
              Object.fromEntries(
                metrics.items.map((item) => [item.series_id, item])
              )
            );
          } catch {
            if (requestId !== searchRequestRef.current) return;
            // Rating filtering is already server-side. Metrics are display-only,
            // so a temporary Social outage must not hide Catalog search results.
            setSocialMetrics({});
          }
        } else {
          setSocialMetrics({});
        }
      } catch (err: any) {
        if (requestId !== searchRequestRef.current) return;
        setHasSearched(true);
        setError(
          err?.detail ||
            err?.message ||
            'Advanced search failed. Showing the last successful results.'
        );
      } finally {
        if (requestId === searchRequestRef.current) setLoading(false);
      }
    },
    [search, status, minRating, sort, selectedGenreIds, selectedTagIds]
  );

  useEffect(() => {
    if (
      searchParams.get('search') ||
      searchParams.get('genre') ||
      searchParams.get('tag') ||
      searchParams.get('status') ||
      searchParams.get('min_rating') ||
      searchParams.get('sort')
    ) {
      void runSearch(0);
    }
    // Initial URL state only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const showPagination = hasSearched && !loading && (series.length > 0 || offset > 0);

  const activeFilterCount =
    selectedGenreIds.length +
    selectedTagIds.length +
    (status ? 1 : 0) +
    (minRating ? 1 : 0) +
    (search.trim() ? 1 : 0);

  const visibleGenres = useMemo(() => {
    const query = genreQuery.trim().toLowerCase();
    if (!query) return genres;

    return genres.filter((genre) =>
      genre.name.toLowerCase().includes(query)
    );
  }, [genreQuery, genres]);

  const visibleTags = useMemo(() => {
    const query = tagQuery.trim().toLowerCase();
    if (!query) return tags;

    return tags.filter((tag) =>
      tag.name.toLowerCase().includes(query)
    );
  }, [tagQuery, tags]);

  const toggleGenre = (id: number) => {
    setSelectedGenreIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id]
    );
  };

  const toggleTag = (id: number) => {
    setSelectedTagIds((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id]
    );
  };

  const handleSearch = () => {
    setOffset(0);
    const params: Record<string, string> = {};

    if (search.trim()) params.search = search.trim();
    if (status) params.status = status;
    if (minRating) params.min_rating = minRating;
    if (sort && sort !== 'relevance') params.sort = sort;
    if (selectedGenreIds.length) {
      params.genre = selectedGenreIds.join(',');
    }
    if (selectedTagIds.length) {
      params.tag = selectedTagIds.join(',');
    }

    setSearchParams(params, { replace: true });
    void runSearch(0);
  };

  const handleReset = () => {
    setSearch('');
    setSelectedGenreIds([]);
    setSelectedTagIds([]);
    setStatus('');
    setMinRating('');
    setSort('relevance');
    setSocialMetrics({});
    setGenreQuery('');
    setTagQuery('');
    setOffset(0);
    setSeries([]);
    setHasSearched(false);
    setError('');
    setSearchParams({}, { replace: true });
  };

  const goToPage = (newOffset: number) => {
    setOffset(newOffset);
    void runSearch(newOffset);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="w-full min-w-0 max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-brand-600/20 text-brand-400 flex items-center justify-center">
          <SlidersHorizontal size={20} />
        </div>

        <div>
          <h1 className="font-display text-3xl font-bold">
            Advanced Search
          </h1>
          <p className="text-ink-400">
            Search and sort the catalog by title, genres, tags, rating, status, and reader popularity.
          </p>
        </div>
      </div>

      {error && (
        <div className="mreader-break-anywhere mb-5 rounded-xl border border-red-800/60 bg-red-950/30 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="grid min-w-0 lg:grid-cols-[320px_minmax(0,1fr)] gap-6">
        <div className="min-w-0 space-y-4">
          <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 space-y-5">
            <div>
              <label className="block text-sm font-medium text-ink-200 mb-2">
                Title
              </label>

              <div className="relative">
                <Search
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400"
                  size={18}
                />
                <input
                  type="text"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') handleSearch();
                  }}
                  placeholder="Search by title…"
                  className="w-full pl-10 pr-4 py-2.5 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 placeholder-ink-500 focus:border-brand-500 focus:outline-none transition-colors text-sm"
                />
              </div>
            </div>

            <div className="border-t border-ink-800 pt-4">
              <label className="mb-2 block text-sm font-medium text-ink-200">Sort results</label>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
                className="w-full rounded-lg border border-ink-800 bg-ink-950 px-3 py-2.5 text-sm text-ink-100 outline-none transition-colors focus:border-brand-500"
              >
                {SORT_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </div>

            <div className="border-t border-ink-800 pt-4">
              <button
                type="button"
                onClick={() => setGenresOpen((open) => !open)}
                className="flex items-center justify-between w-full text-sm font-medium text-ink-200 mb-2"
              >
                <span className="flex items-center gap-2">
                  Genres
                  {selectedGenreIds.length > 0 && (
                    <span className="text-xs bg-brand-600 text-white px-2 py-0.5 rounded-full">
                      {selectedGenreIds.length}
                    </span>
                  )}
                </span>
                {genresOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {genresOpen && (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={genreQuery}
                    onChange={(event) => setGenreQuery(event.target.value)}
                    placeholder="Filter genres…"
                    className="w-full px-3 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 placeholder-ink-500 focus:border-brand-500 focus:outline-none text-xs"
                  />

                  <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
                    {taxonomyLoading ? (
                      <p className="text-xs text-ink-500 px-2 py-3">
                        Loading genres…
                      </p>
                    ) : visibleGenres.length === 0 ? (
                      <p className="text-xs text-ink-500 px-2 py-3">
                        No catalog genres match.
                      </p>
                    ) : (
                      visibleGenres.map((genre) => {
                        const selected = selectedGenreIds.includes(genre.id);

                        return (
                          <label
                            key={genre.id}
                            className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
                              selected
                                ? 'bg-brand-600/20 text-brand-200'
                                : 'hover:bg-ink-800 text-ink-300'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={() => toggleGenre(genre.id)}
                              className="accent-brand-500"
                            />
                            <span className="min-w-0 break-words text-sm">{genre.name}</span>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-ink-800 pt-4">
              <button
                type="button"
                onClick={() => setTagsOpen((open) => !open)}
                className="flex items-center justify-between w-full text-sm font-medium text-ink-200 mb-2"
              >
                <span className="flex items-center gap-2">
                  Tags
                  {selectedTagIds.length > 0 && (
                    <span className="text-xs bg-brand-600 text-white px-2 py-0.5 rounded-full">
                      {selectedTagIds.length}
                    </span>
                  )}
                </span>
                {tagsOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {tagsOpen && (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={tagQuery}
                    onChange={(event) => setTagQuery(event.target.value)}
                    placeholder="Filter tags…"
                    className="w-full px-3 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 placeholder-ink-500 focus:border-brand-500 focus:outline-none text-xs"
                  />

                  <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
                    {taxonomyLoading ? (
                      <p className="text-xs text-ink-500 px-2 py-3">
                        Loading tags…
                      </p>
                    ) : visibleTags.length === 0 ? (
                      <p className="text-xs text-ink-500 px-2 py-3">
                        No catalog tags match.
                      </p>
                    ) : (
                      visibleTags.map((tag) => {
                        const selected = selectedTagIds.includes(tag.id);

                        return (
                          <label
                            key={tag.id}
                            className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
                              selected
                                ? 'bg-brand-600/20 text-brand-200'
                                : 'hover:bg-ink-800 text-ink-300'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={() => toggleTag(tag.id)}
                              className="accent-brand-500"
                            />
                            <span className="min-w-0 break-words text-sm">{tag.name}</span>
                          </label>
                        );
                      })
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="border-t border-ink-800 pt-4">
              <button
                type="button"
                onClick={() => setRatingOpen((open) => !open)}
                className="flex items-center justify-between w-full text-sm font-medium text-ink-200 mb-2"
              >
                <span className="flex items-center gap-2">
                  Minimum Rating
                  {minRating && (
                    <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded-full">
                      {minRating}+
                    </span>
                  )}
                </span>
                {ratingOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {ratingOpen && (
                <div className="space-y-1.5">
                  {RATING_THRESHOLDS.map((item) => (
                    <label
                      key={item.value || 'any-rating'}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                        minRating === item.value
                          ? 'bg-amber-500/15 text-amber-200'
                          : 'hover:bg-ink-800 text-ink-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="min-rating"
                        checked={minRating === item.value}
                        onChange={() => setMinRating(item.value)}
                        className="accent-amber-500"
                      />
                      <Star size={14} className="text-amber-400" fill="currentColor" />
                      <span className="text-sm">{item.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-ink-800 pt-4">
              <button
                type="button"
                onClick={() => setStatusOpen((open) => !open)}
                className="flex items-center justify-between w-full text-sm font-medium text-ink-200 mb-2"
              >
                Series Status
                {statusOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {statusOpen && (
                <div className="space-y-1.5">
                  {STATUSES.map((item) => (
                    <label
                      key={item.value || 'any'}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                        status === item.value
                          ? 'bg-brand-600/20 text-brand-200'
                          : 'hover:bg-ink-800 text-ink-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="status"
                        checked={status === item.value}
                        onChange={() => setStatus(item.value)}
                        className="accent-brand-500"
                      />
                      <span className="text-sm">{item.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-ink-800 pt-4 flex flex-col sm:flex-row gap-2">
              <button
                type="button"
                onClick={handleSearch}
                className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium transition-colors"
              >
                <Search size={16} />
                Search
                {activeFilterCount > 0 && (
                  <span className="text-xs bg-white/15 px-1.5 py-0.5 rounded-full">
                    {activeFilterCount}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={handleReset}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-lg bg-ink-800 hover:bg-ink-700 text-ink-200 text-sm font-medium transition-colors"
              >
                <X size={16} />
                Clear
              </button>
            </div>

            <p className="text-[11px] leading-relaxed text-ink-600">
              Genre and tag options come from the current catalog database and only
              include values assigned to at least one stored series. Selecting
              multiple genres/tags uses AND matching. Rating thresholds are calculated from all logged-in user ratings before pagination.
            </p>
          </div>
        </div>

        <div className="min-w-0 min-h-[60vh]">
          {!hasSearched && !loading ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-20 text-ink-400">
              <SlidersHorizontal size={48} className="mb-4 opacity-40" />
              <p className="text-lg font-medium text-ink-300">
                Select filters and press Search
              </p>
              <p className="text-sm mt-1">
                Combine title, genres, tags, minimum average rating, status, and sorting.
              </p>
            </div>
          ) : loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
              {Array.from({ length: 10 }).map((_, index) => (
                <div
                  key={index}
                  className="skeleton aspect-[2/3] rounded-xl"
                />
              ))}
            </div>
          ) : series.length === 0 ? (
            <div className="text-center py-20 text-ink-400">
              <p className="text-lg">No series match your filters</p>
              <button
                type="button"
                onClick={handleReset}
                className="mt-3 text-brand-400 hover:text-brand-300 text-sm"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <>
              <p className="text-sm text-ink-400 mb-4">
                {series.length} result{series.length === 1 ? '' : 's'} on this page
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4 animate-fade-in">
                {series.map((item) => (
                  <Link
                    key={item.id}
                    to={`/series/${item.slug}`}
                    className="group min-w-0"
                  >
                    <div className="relative aspect-[2/3] rounded-xl overflow-hidden bg-ink-800">
                      {item.cover_image_path ? (
                        <img
                          src={`/images/${item.cover_image_path}`}
                          alt={item.title}
                          loading="lazy"
                          className="w-full h-full object-cover transition-transform group-hover:scale-105"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-ink-700 to-ink-800">
                          <span className="text-3xl font-display font-bold text-ink-500">
                            {item.title[0]}
                          </span>
                        </div>
                      )}

                      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-ink-950 to-transparent p-2">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                            item.status === 'ongoing'
                              ? 'bg-green-600/80'
                              : item.status === 'completed'
                                ? 'bg-blue-600/80'
                                : item.status === 'cancelled'
                                  ? 'bg-red-600/80'
                                  : 'bg-yellow-600/80'
                          }`}
                        >
                          {item.status}
                        </span>
                      </div>
                    </div>

                    <h3 className="mt-2 min-w-0 text-sm font-medium line-clamp-2 break-words group-hover:text-brand-400 transition-colors">
                      {item.title}
                    </h3>

                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
                      <span className="inline-flex items-center gap-1" title="Average rating">
                        <Star size={13} className="text-amber-400" fill="currentColor" />
                        <span className="font-medium text-ink-300">
                          {socialMetrics[item.id]?.rating_average?.toFixed(1) ?? '—'}
                        </span>
                        <span>({socialMetrics[item.id]?.rating_count ?? 0})</span>
                      </span>
                      <span className="inline-flex items-center gap-1" title="Bookmarks">
                        <Bookmark size={13} className="text-brand-400" />
                        {socialMetrics[item.id]?.bookmark_count ?? 0}
                      </span>
                      <span className="inline-flex items-center gap-1" title="Subscribers">
                        <Users size={13} className="text-brand-400" />
                        {socialMetrics[item.id]?.subscription_count ?? 0}
                      </span>
                    </div>

                    {!!item.genres?.length && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {item.genres.slice(0, 3).map((genre) => (
                          <span
                            key={`genre:${genre.id}`}
                            className="max-w-full whitespace-normal break-words text-[10px] px-1.5 py-0.5 rounded-full bg-blue-600/15 text-blue-300"
                          >
                            {genre.name}
                          </span>
                        ))}
                      </div>
                    )}

                    {!!item.tags?.length && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {item.tags.slice(0, 3).map((tag) => (
                          <span
                            key={`tag:${tag.id}`}
                            className="max-w-full whitespace-normal break-words text-[10px] px-1.5 py-0.5 rounded-full bg-brand-600/20 text-brand-300"
                          >
                            {tag.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </Link>
                ))}
              </div>

            </>
          )}

          {showPagination && (
            <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-4 mt-8">
              <button
                type="button"
                onClick={() => goToPage(Math.max(0, offset - LIMIT))}
                disabled={offset === 0}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-200 disabled:opacity-40 hover:bg-ink-700 transition-colors"
              >
                Previous
              </button>
              <span className="text-ink-400 text-sm">
                Page {Math.floor(offset / LIMIT) + 1}
              </span>
              <button
                type="button"
                onClick={() => goToPage(offset + LIMIT)}
                disabled={series.length < LIMIT}
                className="px-4 py-2 rounded-lg bg-ink-800 text-ink-200 disabled:opacity-40 hover:bg-ink-700 transition-colors"
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
