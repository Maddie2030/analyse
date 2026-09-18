import { useReading } from '../reading/useReading';
import { READING_CONFIRMED_EVENT } from '../reading/browser';
import { useCallback, useEffect, useMemo, useRef, useState, type ElementType, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpen, Bookmark, ChevronLeft, ChevronRight, Clock3, Compass, History, Search, Shuffle, SlidersHorizontal, Sparkles, TrendingUp, Flame, Megaphone, X, Star, Eye, Users } from 'lucide-react';
import { api, type Announcement, type CurationResponse, type DiscoverySeries, type EditorPick, type Genre, type SmartLibraryItem, type Series, type SeriesSocialMetrics, type TrendingResponse, type TrendingWindow } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import SeriesPosterCard from '../components/SeriesPosterCard';

const LIMIT = 20;

type Discovery = { popular: Series[]; recent: DiscoverySeries[]; new: Series[] };

function HorizontalScroller({ children }: { children: ReactNode }) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const refreshScrollState = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const maxScrollLeft = Math.max(0, track.scrollWidth - track.clientWidth);
    setCanScrollLeft(track.scrollLeft > 4);
    setCanScrollRight(track.scrollLeft < maxScrollLeft - 4);
  }, []);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    refreshScrollState();

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(refreshScrollState);
    observer?.observe(track);
    window.addEventListener('resize', refreshScrollState);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', refreshScrollState);
    };
  }, [children, refreshScrollState]);

  const move = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (!track) return;
    const distance = Math.max(260, Math.round(track.clientWidth * 0.82));
    track.scrollBy({ left: direction * distance, behavior: 'smooth' });
  };

  return (
    <div className="group/scroller relative min-w-0">
      <div
        ref={trackRef}
        onScroll={refreshScrollState}
        className="grid auto-cols-[42%] grid-flow-col gap-3 overflow-x-auto pb-2 sm:auto-cols-[24%] md:auto-cols-[18%] lg:auto-cols-[14.5%] hide-scrollbar"
      >
        {children}
      </div>

      <button
        type="button"
        onClick={() => move(-1)}
        disabled={!canScrollLeft}
        aria-label="Scroll series left"
        className={`absolute left-1 top-1/2 z-20 hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-ink-950/55 text-white shadow-xl backdrop-blur-md transition md:flex ${canScrollLeft ? 'opacity-75 hover:bg-ink-950/85 hover:opacity-100' : 'pointer-events-none opacity-0'}`}
      >
        <ChevronLeft size={24} />
      </button>
      <button
        type="button"
        onClick={() => move(1)}
        disabled={!canScrollRight}
        aria-label="Scroll series right"
        className={`absolute right-1 top-1/2 z-20 hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-ink-950/55 text-white shadow-xl backdrop-blur-md transition md:flex ${canScrollRight ? 'opacity-75 hover:bg-ink-950/85 hover:opacity-100' : 'pointer-events-none opacity-0'}`}
      >
        <ChevronRight size={24} />
      </button>
    </div>
  );
}

function Shelf({
  title,
  icon: Icon,
  items,
  metrics,
  action,
}: {
  title: string;
  icon: ElementType;
  items: Series[];
  metrics: Record<string, SeriesSocialMetrics>;
  action?: ReactNode;
}) {
  if (!items.length) return null;
  return (
    <section>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex min-w-0 items-center gap-2 font-display text-lg font-bold sm:text-xl">
          <Icon size={20} className="shrink-0 text-brand-400" /> {title}
        </h2>
        {action}
      </div>
      <HorizontalScroller>
        {items.map((item) => <SeriesPosterCard key={item.id} series={item} metrics={metrics[item.id]} dense />)}
      </HorizontalScroller>
    </section>
  );
}

function AnnouncementStack({ items }: { items: Announcement[] }) {
  const [dismissed, setDismissed] = useState<Record<string, boolean>>(() => {
    const out: Record<string, boolean> = {};
    for (const item of items) {
      try { out[item.id] = window.localStorage.getItem(`mreader_announcement_dismissed:${item.id}`) === '1'; } catch { out[item.id] = false; }
    }
    return out;
  });

  useEffect(() => {
    setDismissed((current) => {
      const next = { ...current };
      for (const item of items) {
        if (next[item.id] !== undefined) continue;
        try { next[item.id] = window.localStorage.getItem(`mreader_announcement_dismissed:${item.id}`) === '1'; } catch { next[item.id] = false; }
      }
      return next;
    });
  }, [items]);

  const visible = items.filter((item) => !dismissed[item.id]);
  if (!visible.length) return null;
  const tones: Record<Announcement['tone'], string> = {
    info: 'border-brand-700/50 bg-brand-950/30 text-brand-100',
    success: 'border-green-700/50 bg-green-950/25 text-green-100',
    warning: 'border-amber-700/50 bg-amber-950/25 text-amber-100',
    critical: 'border-red-700/50 bg-red-950/30 text-red-100',
  };

  const dismiss = (item: Announcement) => {
    try { window.localStorage.setItem(`mreader_announcement_dismissed:${item.id}`, '1'); } catch {}
    setDismissed((current) => ({ ...current, [item.id]: true }));
  };

  return (
    <div className="mt-4 space-y-2" aria-label="Site announcements">
      {visible.map((item) => (
        <div key={item.id} className={`flex min-w-0 items-start gap-3 rounded-2xl border px-4 py-3 ${tones[item.tone]}`}>
          <Megaphone size={18} className="mt-0.5 shrink-0 opacity-80" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold break-words">{item.title}</p>
            <p className="mt-0.5 text-sm leading-5 opacity-80 break-words">{item.body}</p>
            {item.link_url && (
              item.link_url.startsWith('/') ? (
                <Link to={item.link_url} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-4">
                  {item.link_label || 'Learn more'} <ArrowRight size={13} />
                </Link>
              ) : (
                <a href={item.link_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-semibold underline underline-offset-4">
                  {item.link_label || 'Learn more'} <ArrowRight size={13} />
                </a>
              )
            )}
          </div>
          {item.dismissible && <button type="button" onClick={() => dismiss(item)} aria-label={`Dismiss ${item.title}`} className="shrink-0 rounded-lg p-1 opacity-60 transition hover:bg-white/10 hover:opacity-100"><X size={16} /></button>}
        </div>
      ))}
    </div>
  );
}

function EditorPicks({ items, metrics }: { items: EditorPick[]; metrics: Record<string, SeriesSocialMetrics> }) {
  if (!items.length) return null;
  return (
    <section>
      <div className="mb-4">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold sm:text-xl"><Star size={20} className="text-amber-400" /> Editor's Picks</h2>
        <p className="mt-1 text-xs text-ink-500 sm:text-sm">Hand-picked recommendations from the MReader team.</p>
      </div>
      <HorizontalScroller>
        {items.map((item) => (
          <div key={item.id} className="min-w-0">
            <div className="relative">
              <SeriesPosterCard series={item.series} metrics={metrics[item.series.id]} dense />
              {item.label && <span className="pointer-events-none absolute left-2 top-2 max-w-[80%] truncate rounded-full bg-amber-500/95 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-ink-950 shadow">{item.label}</span>}
            </div>
            {item.note && <p className="mt-2 line-clamp-2 text-xs leading-4 text-ink-500">{item.note}</p>}
          </div>
        ))}
      </HorizontalScroller>
    </section>
  );
}

function relativeTime(value: string) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '';
  const diffSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (diffSeconds < 60) return 'just now';
  const minutes = Math.floor(diffSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(timestamp));
}

function LatestUpdates({
  items,
  metrics,
  onViewAll,
}: {
  items: DiscoverySeries[];
  metrics: Record<string, SeriesSocialMetrics>;
  onViewAll: () => void;
}) {
  if (!items.length) return null;
  return (
    <section>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-display text-lg font-bold sm:text-xl">
            <Clock3 size={20} className="shrink-0 text-brand-400" /> Latest updates
          </h2>
          <p className="mt-1 text-xs text-ink-500 sm:text-sm">Jump straight into one of the newest published chapters.</p>
        </div>
        <button type="button" onClick={onViewAll} className="shrink-0 text-xs font-medium text-brand-400 hover:text-brand-300">
          See all updated
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <article key={item.id} className="flex min-w-0 gap-3 rounded-2xl border border-ink-800 bg-ink-900/75 p-3 transition hover:border-ink-700 sm:gap-4">
            <Link to={`/series/${item.slug}`} className="w-20 shrink-0 sm:w-24">
              <div className="aspect-[2/3] overflow-hidden rounded-xl bg-ink-800">
                {item.cover_image_path ? (
                  <img src={`/images/${item.cover_image_path}`} alt={item.title} loading="lazy" className="h-full w-full object-cover transition duration-300 hover:scale-105" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-ink-700 to-ink-800 font-display text-2xl font-bold text-ink-500">
                    {item.title[0]}
                  </div>
                )}
              </div>
            </Link>

            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link to={`/series/${item.slug}`} className="line-clamp-2 break-words text-sm font-semibold text-ink-100 transition hover:text-brand-300 sm:text-base">
                    {item.title}
                  </Link>
                  <p className="mt-1 text-[11px] capitalize text-ink-500">{item.status || 'ongoing'}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink-500">
                    <span className="inline-flex items-center gap-1" title="Average rating"><Star size={11} className="text-amber-400" fill="currentColor" />{metrics[item.id]?.rating_average?.toFixed(1) ?? '—'}</span>
                    <span className="inline-flex items-center gap-1" title="Bookmarks"><Bookmark size={11} className="text-brand-400" />{metrics[item.id]?.bookmark_count ?? 0}</span>
                    <span className="inline-flex items-center gap-1" title="Subscribers"><Users size={11} className="text-brand-400" />{metrics[item.id]?.subscription_count ?? 0}</span>
                  </div>
                </div>
                <BookOpen size={17} className="mt-0.5 shrink-0 text-ink-600" />
              </div>

              <div className="mt-3 space-y-1.5">
                {(item.latest_chapters || []).slice(0, 3).map((chapter) => (
                  <Link
                    key={`${item.id}-${chapter.slug}`}
                    to={`/read/${item.slug}/${chapter.slug}`}
                    className="group/chapter flex min-w-0 items-center gap-2 rounded-lg bg-ink-950/70 px-2.5 py-2 text-xs transition hover:bg-brand-600/10"
                  >
                    <span className="shrink-0 font-semibold text-brand-300">Ch. {chapter.chapter_number}</span>
                    {chapter.title && <span className="min-w-0 flex-1 truncate text-ink-400 group-hover/chapter:text-ink-200">{chapter.title}</span>}
                    <span className="ml-auto shrink-0 text-[10px] text-ink-600">{relativeTime(chapter.published_at)}</span>
                    <ArrowRight size={13} className="shrink-0 text-ink-700 group-hover/chapter:text-brand-400" />
                  </Link>
                ))}
                {!item.latest_chapters?.length && (
                  <Link to={`/series/${item.slug}`} className="inline-flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300">
                    View chapters <ArrowRight size={13} />
                  </Link>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}


function TrendingShelf({
  response,
  window,
  loading,
  metrics,
  onWindowChange,
  fallback,
}: {
  response: TrendingResponse | null;
  window: TrendingWindow;
  loading: boolean;
  metrics: Record<string, SeriesSocialMetrics>;
  onWindowChange: (window: TrendingWindow) => void;
  fallback: Series[];
}) {
  const items = response?.items || [];
  const windows: Array<{ value: TrendingWindow; label: string }> = [
    { value: '24h', label: '24h' }, { value: '7d', label: '7d' }, { value: '30d', label: '30d' },
  ];

  if (loading && !response) {
    return <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">{Array.from({ length: 6 }).map((_, index) => <div key={index} className="skeleton aspect-[2/3] rounded-xl" />)}</div>;
  }
  if (!items.length) {
    return <Shelf title="Popular with readers" icon={TrendingUp} items={fallback} metrics={metrics} action={<span className="text-[10px] uppercase tracking-wider text-ink-600">All time</span>} />;
  }

  return (
    <section>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 font-display text-lg font-bold sm:text-xl"><Flame size={20} className="text-orange-400" /> Trending now</h2>
          <p className="mt-1 text-xs text-ink-500 sm:text-sm">Ranked from deduplicated chapter opens, not all-time bookmarks.</p>
        </div>
        <div className="inline-flex w-fit rounded-xl bg-ink-900 p-1" aria-label="Trending time window">
          {windows.map((option) => (
            <button key={option.value} type="button" onClick={() => onWindowChange(option.value)} className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition ${window === option.value ? 'bg-brand-600 text-white' : 'text-ink-400 hover:text-ink-200'}`}>{option.label}</button>
          ))}
        </div>
      </div>
      <HorizontalScroller>
        {items.map((item, index) => (
          <div key={item.id} className="relative min-w-0">
            <div className="pointer-events-none absolute left-2 top-2 z-10 flex h-7 min-w-7 items-center justify-center rounded-full bg-ink-950/90 px-2 text-xs font-bold text-white ring-1 ring-white/10">#{index + 1}</div>
            <SeriesPosterCard series={item} metrics={metrics[item.id]} dense />
            <p className="mt-1 inline-flex items-center gap-1 text-[10px] text-ink-500"><Eye size={11} aria-hidden="true" /> {item.trend_score.toLocaleString()} {item.trend_score === 1 ? 'view' : 'views'}</p>
          </div>
        ))}
      </HorizontalScroller>
    </section>
  );
}

function ContinueReading({ items }: { items: SmartLibraryItem[] }) {
  const { repository } = useReading();
  const pendingBySeries = new Map(
    (repository?.records() || [])
      .filter((record) => record.command || record.dirty)
      .sort((a, b) => a.touched - b.touched || a.created - b.created)
      .map((record) => [record.target.series_id, record] as const),
  );
  if (!items.length && pendingBySeries.size === 0) return null;
  return (
    <section>
      <div className="mb-4 flex items-center gap-2">
        <History size={20} className="text-brand-400" />
        <h2 className="font-display text-lg font-bold sm:text-xl">Continue reading</h2>
        <Link to="/library" className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand-400 hover:text-brand-300">Library <ArrowRight size={14} /></Link>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => {
          const pending = pendingBySeries.get(item.series_id);
          pendingBySeries.delete(item.series_id);
          return (
          <Link key={item.series_id} to={pending ? `/read/${pending.target.series_slug}/${pending.target.chapter_slug}` : item.reading_available && item.reading_action ? `/read/${item.series_slug}/${item.reading_action.chapter_slug}` : `/series/${item.series_slug}`} className="group flex min-w-0 items-center gap-3 rounded-2xl border border-ink-800 bg-ink-900/80 px-4 py-3 transition hover:border-brand-600/50 hover:bg-ink-900">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-600/15 text-brand-400"><History size={19} /></div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink-200 group-hover:text-brand-300">{item.series_title}</p>
              <p className="truncate text-xs text-ink-500">{pending ? `Local page ${pending.position.last_page} · ${pending.paused ? 'Sync paused' : 'Saving'}` : item.reading_available ? `Continue chapter ${item.resume_chapter_number ?? ""}` : "Reading unavailable"}</p>
            </div>
            <ArrowRight size={17} className="shrink-0 text-ink-600 transition group-hover:translate-x-0.5 group-hover:text-brand-400" />
          </Link>
          );
        })}
      </div>
      {repository?.storageError && <p className="mt-2 text-xs text-amber-300" role="status">{repository.storageError}</p>}
      {[...pendingBySeries.values()].map(r => <Link key={r.target.series_id} className="mt-2 block text-xs text-amber-300" to={`/read/${r.target.series_slug}/${r.target.chapter_slug}`}>Local resume · {r.target.series_slug} · Page {r.position.last_page} · {r.paused ? 'Sync paused' : 'Saving'}</Link>)}
    </section>
  );
}

export default function Catalog() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [series, setSeries] = useState<Series[]>([]);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [search, setSearch] = useState('');
  const [activeGenre, setActiveGenre] = useState<number | null>(null);
  const [sort, setSort] = useState('relevance');
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [discovery, setDiscovery] = useState<Discovery>({ popular: [], recent: [], new: [] });
  const [discoveryLoading, setDiscoveryLoading] = useState(true);
  const [history, setHistory] = useState<SmartLibraryItem[]>([]);
  const [socialMetrics, setSocialMetrics] = useState<Record<string, SeriesSocialMetrics>>({});
  const [trendingWindow, setTrendingWindow] = useState<TrendingWindow>('24h');
  const [trending, setTrending] = useState<TrendingResponse | null>(null);
  const [trendingLoading, setTrendingLoading] = useState(true);
  const [curation, setCuration] = useState<CurationResponse>({ editor_picks: [], announcements: [] });
  const [catalogError, setCatalogError] = useState('');
  const seriesRequestRef = useRef(0);

  const mergeMetrics = useCallback(async (items: Series[]) => {
    const ids = Array.from(new Set(items.map((item) => item.id)));
    if (!ids.length) return;
    try {
      const response = await api.seriesSocialMetricsBatch(ids);
      setSocialMetrics((current) => ({
        ...current,
        ...Object.fromEntries(response.items.map((item) => [item.series_id, item])),
      }));
    } catch {
      // Social metrics are display-only; browsing must survive a Social outage.
    }
  }, []);

  useEffect(() => {
    api.getGenres().then(setGenres).catch(() => {});
    api.getCuration().then((data) => {
      setCuration({ editor_picks: data.editor_picks || [], announcements: data.announcements || [] });
      void mergeMetrics((data.editor_picks || []).map((item) => item.series));
    }).catch(() => { /* Preserve last successful curation on transient failure. */ });

    let cancelled = false;
    setDiscoveryLoading(true);
    api.getDiscovery()
      .then((data) => {
        if (cancelled) return;
        const next: Discovery = {
          popular: data.popular || [],
          recent: (data.recent || []).map((item) => ({
            ...item,
            latest_chapters: item.latest_chapters || [],
          })),
          new: data.new || [],
        };
        setDiscovery(next);
        void mergeMetrics([...next.popular, ...next.recent, ...next.new]);
      })
      .catch(() => {
        // Keep the previous discovery snapshot; a failed refresh is not an empty catalog.
      })
      .finally(() => {
        if (!cancelled) setDiscoveryLoading(false);
      });

    return () => { cancelled = true; };
  }, [mergeMetrics]);

  useEffect(() => {
    let cancelled = false;
    setTrendingLoading(true);
    api.getTrending(trendingWindow, 10)
      .then((data) => {
        if (cancelled) return;
        setTrending(data);
        void mergeMetrics(data.items);
      })
      .catch(() => { /* Keep the previous trending snapshot on refresh failure. */ })
      .finally(() => { if (!cancelled) setTrendingLoading(false); });
    return () => { cancelled = true; };
  }, [trendingWindow, mergeMetrics]);

  useEffect(() => {
    if (!user) {
      setHistory([]);
      return;
    }
    let generation = 0;
    let cancelled = false;
    const load = () => {
      const request = ++generation;
      void api.getSmartLibrary({ scope: 'history', state: 'all', sort: 'activity', limit: 6, offset: 0 }).then(response => {
        if (response.contract_version !== 1 || response.request_identity.scope !== 'history' || response.request_identity.state !== 'all' ||
            response.request_identity.sort !== 'activity' || response.request_identity.offset !== 0 || response.request_identity.limit !== 6) {
          throw new Error('Library response identity mismatch');
        }
        if (!cancelled && request === generation) setHistory(response.recently_opened.items.slice(0, 6));
      }).catch(() => {});
    };
    setHistory([]);
    load();
    window.addEventListener(READING_CONFIRMED_EVENT, load);
    return () => { cancelled = true; window.removeEventListener(READING_CONFIRMED_EVENT, load); };
  }, [user?.id]);

  const fetchSeries = useCallback(async () => {
    const requestId = ++seriesRequestRef.current;
    setLoading(true);
    const params = new URLSearchParams();
    if (search.trim()) params.set('search', search.trim());
    if (activeGenre !== null) params.set('genre', String(activeGenre));
    params.set('sort', sort);
    params.set('offset', String(offset));
    params.set('limit', String(LIMIT));
    try {
      const data = await api.listSeries(`?${params.toString()}`);
      if (requestId !== seriesRequestRef.current) return;
      setSeries(data);
      setCatalogError('');
      void mergeMetrics(data);
    } catch {
      if (requestId !== seriesRequestRef.current) return;
      // Preserve prior results instead of presenting a transient outage as an
      // empty catalog. The visible warning makes the stale snapshot explicit.
      setCatalogError('Catalog refresh failed. Showing the last successful results.');
    } finally {
      if (requestId === seriesRequestRef.current) setLoading(false);
    }
  }, [search, activeGenre, sort, offset, mergeMetrics]);

  useEffect(() => {
    const timer = setTimeout(() => { void fetchSeries(); }, search ? 250 : 0);
    return () => clearTimeout(timer);
  }, [fetchSeries, search]);

  const discoveryPool = useMemo(() => {
    const map = new Map<string, Series>();
    [...curation.editor_picks.map((item) => item.series), ...(trending?.items || []), ...discovery.popular, ...discovery.recent, ...discovery.new, ...series].forEach((item) => map.set(item.id, item));
    return Array.from(map.values());
  }, [curation.editor_picks, trending, discovery, series]);

  const surpriseMe = () => {
    if (!discoveryPool.length) return;
    const item = discoveryPool[Math.floor(Math.random() * discoveryPool.length)];
    navigate(`/series/${item.slug}`);
  };

  const submitHeroSearch = () => {
    const query = search.trim();
    if (!query) return;
    navigate(`/advanced-search?search=${encodeURIComponent(query)}`);
  };

  return (
    <div className="mx-auto w-full min-w-0 max-w-7xl px-3 py-6 sm:px-4 sm:py-8 animate-fade-in">
      {catalogError && (
        <div className="mb-4 rounded-xl border border-amber-700/50 bg-amber-950/25 px-4 py-3 text-sm text-amber-200">
          {catalogError}
        </div>
      )}
      <section className="relative overflow-hidden rounded-3xl border border-ink-800 bg-gradient-to-br from-ink-900 via-ink-900 to-brand-950/30 px-4 py-7 sm:px-7 sm:py-9">
        <div className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-brand-600/10 blur-3xl" />
        <div className="relative max-w-3xl">
          <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-brand-400"><Compass size={15} /> Browse & discover</p>
          <h1 className="font-display text-3xl font-bold leading-tight sm:text-4xl">Find the next series worth losing sleep over.</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-400 sm:text-base">Live trending, recent chapter updates, new releases, and the full catalog live in one reader-first browse experience.</p>

          <form
            className="mt-6 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              submitHeroSearch();
            }}
          >
            <div className="relative min-w-0 flex-1">
              <button type="submit" aria-label="Search series" className="absolute left-2 top-1/2 z-10 -translate-y-1/2 rounded-lg p-1 text-ink-400 transition hover:bg-ink-800 hover:text-brand-300">
                <Search size={19} />
              </button>
              <input
                type="search"
                value={search}
                onChange={(event) => { setSearch(event.target.value); setOffset(0); }}
                placeholder="Search series by title… (Enter to search)"
                className="w-full rounded-xl border border-ink-700 bg-ink-950/80 py-3 pl-10 pr-4 text-ink-100 placeholder-ink-500 outline-none transition focus:border-brand-500"
              />
            </div>
            <Link to="/advanced-search" className="inline-flex items-center justify-center gap-2 rounded-xl border border-ink-700 bg-ink-800 px-4 py-3 text-sm font-semibold text-ink-200 transition hover:border-brand-600/50 hover:text-white">
              <SlidersHorizontal size={18} /> Filters
            </Link>
            <button type="button" onClick={surpriseMe} disabled={!discoveryPool.length} className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-brand-500 disabled:opacity-40">
              <Shuffle size={18} /> Surprise me
            </button>
          </form>
          {search.trim() && (
            <div className="relative z-40 mt-2 overflow-hidden rounded-xl border border-ink-700 bg-ink-950/98 shadow-2xl backdrop-blur">
              {loading ? (
                <div className="px-4 py-3 text-sm text-ink-500">Searching…</div>
              ) : series.length ? (
                <>
                  <div className="max-h-72 overflow-y-auto py-1">
                    {series.slice(0, 6).map((item) => (
                      <Link key={item.id} to={`/series/${item.slug}`} className="flex min-w-0 items-center gap-3 px-3 py-2.5 transition hover:bg-ink-900">
                        <div className="h-12 w-8 shrink-0 overflow-hidden rounded bg-ink-800">
                          {item.cover_image_path ? <img src={`/images/${item.cover_image_path}`} alt="" className="h-full w-full object-cover" /> : null}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-ink-100">{item.title}</p>
                          <p className="truncate text-xs capitalize text-ink-500">{item.status || 'ongoing'}</p>
                        </div>
                        <ArrowRight size={15} className="shrink-0 text-ink-600" />
                      </Link>
                    ))}
                  </div>
                  <button type="button" onClick={submitHeroSearch} className="flex w-full items-center justify-center gap-2 border-t border-ink-800 px-4 py-2.5 text-xs font-semibold text-brand-300 transition hover:bg-brand-600/10 hover:text-brand-200">
                    View all results for “{search.trim()}” <ArrowRight size={14} />
                  </button>
                </>
              ) : (
                <div className="px-4 py-3 text-sm text-ink-500">No matching series found.</div>
              )}
            </div>
          )}
          <p className="mt-2 hidden text-xs text-ink-600 sm:block">Tip: press Ctrl/⌘ + K anywhere to open advanced search.</p>
        </div>
      </section>

      <AnnouncementStack items={curation.announcements} />

      <div className="mt-9 space-y-10">
        <ContinueReading items={history} />

        {discoveryLoading ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, index) => <div key={index} className="skeleton aspect-[2/3] rounded-xl" />)}
          </div>
        ) : (
          <>
            <EditorPicks items={curation.editor_picks} metrics={socialMetrics} />
            <TrendingShelf response={trending} window={trendingWindow} loading={trendingLoading} metrics={socialMetrics} onWindowChange={setTrendingWindow} fallback={discovery.popular} />
            <LatestUpdates
              items={discovery.recent}
              metrics={socialMetrics}
              onViewAll={() => {
                setSearch('');
                setActiveGenre(null);
                setSort('updated');
                setOffset(0);
                window.requestAnimationFrame(() => document.getElementById('all-series')?.scrollIntoView({ behavior: 'smooth' }));
              }}
            />
            <Shelf title="New releases" icon={Sparkles} items={discovery.new} metrics={socialMetrics} />
          </>
        )}

        <section id="all-series" className="scroll-mt-24 border-t border-ink-800 pt-8">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-500">Catalog</p>
              <h2 className="mt-1 font-display text-2xl font-bold">Explore all series</h2>
              <p className="mt-1 text-sm text-ink-500">Use quick genre chips here or open the full filter panel for tags, status, and rating.</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <label className="flex items-center gap-2 rounded-xl bg-ink-800 px-3 py-2 text-xs text-ink-400">
                Sort
                <select value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0); }} className="bg-transparent text-sm font-medium text-ink-200 outline-none">
                  <option value="relevance">Best match</option>
                  <option value="updated">Recently updated</option>
                  <option value="newest">Newest series</option>
                  <option value="rating">Highest rated</option>
                  <option value="popular">Most bookmarked</option>
                  <option value="title">Title A–Z</option>
                </select>
              </label>
              <Link to="/advanced-search" className="inline-flex items-center justify-center gap-2 rounded-xl bg-ink-800 px-4 py-2.5 text-sm font-medium text-ink-200 hover:bg-ink-700">
                <SlidersHorizontal size={17} /> Advanced filters
              </Link>
            </div>
          </div>

          <div className="mb-6 flex gap-2 overflow-x-auto pb-1 hide-scrollbar">
            <button type="button" onClick={() => { setActiveGenre(null); setOffset(0); }} className={`whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium transition ${activeGenre === null ? 'bg-brand-600 text-white' : 'bg-ink-800 text-ink-300 hover:bg-ink-700'}`}>All genres</button>
            {genres.map((genre) => (
              <button key={genre.id} type="button" onClick={() => { setActiveGenre(genre.id); setOffset(0); }} className={`whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium transition ${activeGenre === genre.id ? 'bg-brand-600 text-white' : 'bg-ink-800 text-ink-300 hover:bg-ink-700'}`}>{genre.name}</button>
            ))}
          </div>

          {loading ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {Array.from({ length: 10 }).map((_, index) => <div key={index} className="skeleton aspect-[2/3] rounded-xl" />)}
            </div>
          ) : series.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-ink-700 py-16 text-center text-ink-400">
              <Search size={24} className="mx-auto mb-3 text-ink-600" />
              <p className="font-medium text-ink-300">No series found</p>
              <p className="mt-1 text-sm text-ink-500">Try a different title or genre.</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
              {series.map((item) => <SeriesPosterCard key={item.id} series={item} metrics={socialMetrics[item.id]} />)}
            </div>
          )}

          {!loading && (series.length > 0 || offset > 0) && (
            <div className="mt-8 flex flex-wrap items-center justify-center gap-2 sm:gap-4">
              <button type="button" onClick={() => setOffset(Math.max(0, offset - LIMIT))} disabled={offset === 0} className="rounded-lg bg-ink-800 px-4 py-2 text-ink-200 transition hover:bg-ink-700 disabled:opacity-40">Previous</button>
              <span className="text-sm text-ink-400">Page {Math.floor(offset / LIMIT) + 1}</span>
              <button type="button" onClick={() => setOffset(offset + LIMIT)} disabled={series.length < LIMIT} className="rounded-lg bg-ink-800 px-4 py-2 text-ink-200 transition hover:bg-ink-700 disabled:opacity-40">Next</button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
