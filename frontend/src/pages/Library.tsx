import { useAuth } from '../hooks/useAuth';
import { useReading } from '../reading/useReading';
import { READING_CONFIRMED_EVENT } from '../reading/browser';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  Bell,
  BookOpen,
  Bookmark,
  CheckCircle2,
  Clock3,
  Compass,
  History,
  Layers3,
  Sparkles,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  api,
  type SmartLibraryItem,
  type SmartLibraryResponse,
  type SmartLibraryScope,
  type SmartLibrarySort,
  type SmartLibraryState,
  type SmartLibrarySummary,
} from '../api/client';

const PAGE_SIZE = 48;

const EMPTY_SUMMARY: SmartLibrarySummary = {
  all: 0,
  bookmarks: 0,
  following: 0,
  history: 0,
  updates: 0,
  caught_up: 0,
  not_started: 0,
};

function chapterNumber(value: number | null): string {
  if (value === null) return '—';
  return Number.isInteger(value) ? String(value) : String(value).replace(/0+$/, '').replace(/\.$/, '');
}

function relativeTime(value: string | null): string {
  if (!value) return '';
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return '';
  const seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-700 bg-ink-900/50 px-5 py-12 text-center">
      <p className="font-display text-lg font-semibold text-ink-200">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">{body}</p>
      <Link
        to="/"
        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-500"
      >
        <Compass size={17} /> Browse series
      </Link>
    </div>
  );
}

function StateBadge({ item }: { item: SmartLibraryItem }) {
  if (item.read_state === 'updates') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-brand-500/15 px-2.5 py-1 text-[11px] font-semibold text-brand-300">
        <Sparkles size={12} /> {item.unread_chapter_count} new
      </span>
    );
  }
  if (item.read_state === 'caught_up') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
        <CheckCircle2 size={12} /> Caught up
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ink-700 px-2.5 py-1 text-[11px] font-semibold text-ink-300">
      <BookOpen size={12} /> Not started
    </span>
  );
}

function SmartLibraryCard({ item }: { item: SmartLibraryItem }) {
  const { pending } = useReading(item.series_id);
  const action = item.reading_available ? item.reading_action : null;
  const primary = pending ? { href: `/read/${item.series_slug}/${pending.chapter_slug}`, label: `Local resume · Page ${pending.last_page}` }
    : action ? { href: `/read/${item.series_slug}/${action.chapter_slug}`, label: action.kind === 'start' ? 'Start reading' : action.kind === 'next' ? 'Read next' : 'Continue reading' }
    : { href: `/series/${item.series_slug}`, label: 'Reading unavailable' };

  return (
    <article className="group flex min-w-0 gap-3 rounded-2xl border border-ink-800 bg-ink-900/80 p-3 transition-colors hover:border-ink-700 sm:gap-4 sm:p-4">
      <Link
        to={`/series/${item.series_slug}`}
        className="relative h-32 w-20 shrink-0 overflow-hidden rounded-xl bg-ink-800 sm:h-40 sm:w-28"
      >
        {item.series_cover ? (
          <img
            src={`/images/${item.series_cover}`}
            alt={item.series_title}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-ink-700 to-ink-800">
            <span className="font-display text-3xl font-bold text-ink-500">{item.series_title[0]}</span>
          </div>
        )}
      </Link>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="min-w-0">
            <Link
              to={`/series/${item.series_slug}`}
              className="line-clamp-2 break-words font-display text-base font-semibold text-ink-100 transition-colors group-hover:text-brand-300"
            >
              {item.series_title}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <StateBadge item={item} />
              {item.bookmarked && (
                <span className="inline-flex items-center gap-1 rounded-full bg-ink-800 px-2 py-1 text-[10px] text-ink-400">
                  <Bookmark size={10} /> Saved
                </span>
              )}
              {item.followed && (
                <span className="inline-flex items-center gap-1 rounded-full bg-ink-800 px-2 py-1 text-[10px] text-ink-400">
                  <Bell size={10} /> Subscribed
                </span>
              )}
            </div>
          </div>
          <span className="shrink-0 text-[10px] capitalize text-ink-500">{item.series_status}</span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div className="min-w-0">
            <span className="text-ink-500">Reached</span>
            <p className="truncate font-medium text-ink-300">
              {item.furthest_chapter_number === null ? 'Not started' : `Ch. ${chapterNumber(item.furthest_chapter_number)}`}
            </p>
          </div>
          <div className="min-w-0">
            <span className="text-ink-500">Latest</span>
            <p className="truncate font-medium text-ink-300">
              {item.latest_chapter_number === null ? 'No chapters' : `Ch. ${chapterNumber(item.latest_chapter_number)}`}
            </p>
          </div>
        </div>

        <div className="mt-2 min-h-5 text-[11px] text-ink-500">
          {item.read_state === 'updates' ? (
            <span>{item.unread_chapter_count} chapter{item.unread_chapter_count === 1 ? '' : 's'} waiting</span>
          ) : item.read_state === 'not_started' ? (
            <span>{item.published_chapter_count} chapter{item.published_chapter_count === 1 ? '' : 's'} available</span>
          ) : item.read_at ? (
            <span>Last opened {relativeTime(item.read_at)}</span>
          ) : null}
          {item.latest_published_at && item.read_state !== 'caught_up' && (
            <span className="ml-2">· Updated {relativeTime(item.latest_published_at)}</span>
          )}
        </div>

        {pending && <p className="mt-2 text-xs text-amber-300" role="status">{pending.status} · Local reading preview</p>}
        <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
          <Link
            to={primary.href}
            className="inline-flex min-w-0 items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-500"
          >
            <BookOpen size={14} /> <span className="truncate">{primary.label}</span>
          </Link>
          <Link
            to={`/series/${item.series_slug}`}
            className="inline-flex items-center gap-1 rounded-lg border border-ink-700 px-3 py-2 text-xs font-medium text-ink-300 hover:border-ink-600 hover:text-ink-100"
          >
            Series <ArrowRight size={13} />
          </Link>
          {item.read_state === 'updates' && item.resume_chapter_slug && item.resume_chapter_slug !== item.next_chapter_slug && (
            <Link
              to={`/read/${item.series_slug}/${item.resume_chapter_slug}`}
              className="text-[11px] text-ink-500 hover:text-ink-300"
            >
              Resume Ch. {chapterNumber(item.resume_chapter_number)}
            </Link>
          )}
        </div>
      </div>
    </article>
  );
}

export default function Library() {
  const { user } = useAuth();
  const { repository } = useReading();
  const [recent, setRecent] = useState<SmartLibraryResponse['recently_opened']>({ items: [], total: 0 });
  const [scope, setScope] = useState<SmartLibraryScope>('all');
  const [stateFilter, setStateFilter] = useState<SmartLibraryState>('all');
  const [sort, setSort] = useState<SmartLibrarySort>('activity');
  const [items, setItems] = useState<SmartLibraryItem[]>([]);
  const [summary, setSummary] = useState<SmartLibrarySummary>(EMPTY_SUMMARY);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [libraryKnown, setLibraryKnown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const requestRef = useRef(0);
  const nextOffsetRef = useRef(0);
  const hasLoadedRef = useRef(false);
  const refreshingRequestRef = useRef(false);


  const load = useCallback(async (offset = 0, append = false) => {
    if (append && refreshingRequestRef.current) return;
    const requestId = ++requestRef.current;
    if (append) setLoadingMore(true);
    else { refreshingRequestRef.current = true; setRefreshing(hasLoadedRef.current); setLoading(!hasLoadedRef.current); }
    try {
      const response: SmartLibraryResponse = await api.getSmartLibrary({
        scope,
        state: stateFilter,
        sort,
        offset,
        limit: PAGE_SIZE,
      });
      if (requestId !== requestRef.current) return;
      if (response.contract_version !== 1 || response.request_identity.scope !== scope || response.request_identity.state !== stateFilter || response.request_identity.sort !== sort || response.request_identity.offset !== offset || response.request_identity.limit !== PAGE_SIZE) throw new Error("Library response identity mismatch");
      nextOffsetRef.current = response.offset + response.items.length;
      setItems((current) => append ? [...new Map([...current, ...response.items].map(item => [item.series_id, item])).values()] : response.items);
      if (!append) { setSummary(response.summary); setRecent(response.recently_opened); }
      setTotal(response.total);
      setHasMore(response.has_more);
      setLibraryKnown(true);
      hasLoadedRef.current = true;
      setError('');
    } catch {
      if (requestId !== requestRef.current) return;
      setError(hasLoadedRef.current ? 'Library refresh failed. Showing the last successful snapshot.' : 'Library is unavailable. Retry to load your personal library.');
    } finally {
      if (requestId === requestRef.current) {
        if (!append) refreshingRequestRef.current = false;
        setLoading(false);
        setRefreshing(false);
        setLoadingMore(false);
      }
    }
  }, [scope, sort, stateFilter, user?.id]);

  useEffect(() => {
    requestRef.current++;
    hasLoadedRef.current = false;
    setItems([]); setSummary(EMPTY_SUMMARY); setRecent({ items: [], total: 0 }); setTotal(0); setHasMore(false); setLibraryKnown(false);
    void load(0, false);
    const refresh = () => { void load(0, false); };
    window.addEventListener(READING_CONFIRMED_EVENT, refresh);
    return () => { requestRef.current++; refreshingRequestRef.current = false; window.removeEventListener(READING_CONFIRMED_EVENT, refresh); };
  }, [load]);


  const scopes = useMemo(() => [
    { key: 'all' as const, label: 'All', icon: Layers3, count: summary.all },
    { key: 'bookmarks' as const, label: 'Bookmarks', icon: Bookmark, count: summary.bookmarks },
    { key: 'following' as const, label: 'Subscriptions', icon: Bell, count: summary.following },
    { key: 'history' as const, label: 'History', icon: History, count: summary.history },
  ], [summary]);

  const stateOptions = [
    { key: 'all' as const, label: 'All states', count: summary.all },
    { key: 'updates' as const, label: 'Updates', count: summary.updates },
    { key: 'caught_up' as const, label: 'Caught up', count: summary.caught_up },
    { key: 'not_started' as const, label: 'Not started', count: summary.not_started },
  ];

  const emptyCopy = stateFilter === 'updates'
    ? { title: 'No unread updates', body: 'Anything you have reached is currently caught up. New chapters will surface here automatically.' }
    : stateFilter === 'caught_up'
      ? { title: 'Nothing caught up in this view', body: 'Series with no published chapters after your furthest reached chapter appear here.' }
      : stateFilter === 'not_started'
        ? { title: 'Nothing waiting to be started', body: 'Save or follow a series before reading it and it will appear here.' }
        : { title: 'Your Library is empty', body: 'Bookmark, follow, or start reading a series and it will become part of your Smart Library.' };
  const unmatchedPending = [...new Map(
    (repository?.records() || [])
      .filter(r => (r.command || r.dirty) && !recent.items.some(item => item.series_id === r.target.series_id))
      .sort((a, b) => a.touched - b.touched || a.created - b.created)
      .map(r => [r.target.series_id, r] as const),
  ).values()];

  return (
    <div className="mx-auto w-full min-w-0 max-w-7xl px-3 py-6 sm:px-4 sm:py-8 animate-fade-in">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-brand-400">Personal</p>
          <h1 className="font-display text-2xl font-bold sm:text-3xl">Smart Library</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-400">
            See what has new chapters, what you're caught up on, and exactly where to continue—without hunting through separate lists.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 sm:min-w-[360px]">
          <button type="button" onClick={() => { setScope('all'); setStateFilter('updates'); }} className="rounded-xl border border-brand-500/20 bg-brand-500/10 px-3 py-2 text-left hover:border-brand-500/40">
            <p className="text-[10px] uppercase tracking-wide text-brand-300">Updates</p>
            <p className="mt-0.5 font-display text-xl font-bold text-ink-100">{libraryKnown ? summary.updates : '—'}</p>
          </button>
          <button type="button" onClick={() => { setScope('all'); setStateFilter('caught_up'); }} className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-left hover:border-emerald-500/40">
            <p className="text-[10px] uppercase tracking-wide text-emerald-300">Caught up</p>
            <p className="mt-0.5 font-display text-xl font-bold text-ink-100">{libraryKnown ? summary.caught_up : '—'}</p>
          </button>
          <button type="button" onClick={() => { setScope('all'); setStateFilter('not_started'); }} className="rounded-xl border border-ink-700 bg-ink-900 px-3 py-2 text-left hover:border-ink-600">
            <p className="text-[10px] uppercase tracking-wide text-ink-400">Not started</p>
            <p className="mt-0.5 font-display text-xl font-bold text-ink-100">{libraryKnown ? summary.not_started : '—'}</p>
          </button>
        </div>
      </div>


      {error && (
        <div className="mb-4 rounded-xl border border-amber-700/50 bg-amber-950/25 px-4 py-3 text-sm text-amber-200">
          {error}
        </div>
      )}

      <div className="mb-5 flex gap-1 overflow-x-auto border-b border-ink-800 hide-scrollbar">
        {scopes.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setScope(item.key)}
            aria-pressed={scope === item.key}
            className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition-colors sm:px-4 ${
              scope === item.key ? 'border-brand-400 text-brand-400' : 'border-transparent text-ink-400 hover:text-ink-200'
            }`}
          >
            <item.icon size={17} /> {item.label}
            <span className="rounded-full bg-ink-800 px-1.5 py-0.5 text-[11px] text-ink-300">{libraryKnown ? item.count : '—'}</span>
          </button>
        ))}
      </div>

      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-ink-800 bg-ink-900/60 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-2 overflow-x-auto hide-scrollbar">
          {stateOptions.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setStateFilter(option.key)}
              aria-pressed={stateFilter === option.key}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                stateFilter === option.key
                  ? 'bg-brand-600 text-white'
                  : 'bg-ink-800 text-ink-400 hover:text-ink-200'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="flex shrink-0 items-center gap-2 text-xs text-ink-500">
          Sort
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as SmartLibrarySort)}
            className="rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-ink-200 outline-none focus:border-brand-500"
          >
            <option value="activity">Recent activity</option>
            <option value="updated">Newest updates</option>
            <option value="unread">Most unread</option>
            <option value="title">Title A–Z</option>
          </select>
        </label>
      </div>

      {repository?.storageError && <p className="mb-3 text-sm text-amber-300" role="status">{repository.storageError}</p>}
      {refreshing && (
        <div className="mb-3 flex items-center justify-end gap-2 text-[11px] text-ink-500" role="status" aria-live="polite">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400" /> Updating library…
        </div>
      )}

      {(scope === 'all' || scope === 'history') && stateFilter === 'all' && (recent.items.length > 0 || repository?.hasPending()) && (
        <section className="mb-6">
          <h2 className="mb-3 font-display text-lg">Recently opened <span className="text-xs text-ink-500">{recent.total} series</span></h2>
          <div className="grid gap-3 lg:grid-cols-2">{recent.items.map(item => <SmartLibraryCard key={item.series_id} item={item} />)}</div>
          {unmatchedPending.map(r => (
            <Link key={r.target.series_id} className="mt-2 block text-sm text-amber-300" to={`/read/${r.target.series_slug}/${r.target.chapter_slug}`}>
              Local reading preview · {r.target.series_slug} · Page {r.position.last_page} · {r.paused ? 'Sync paused' : 'Saving'}
            </Link>
          ))}
        </section>
      )}
      {loading ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="flex gap-4 rounded-2xl border border-ink-800 bg-ink-900 p-4">
              <div className="skeleton h-40 w-28 shrink-0 rounded-xl" />
              <div className="flex-1 space-y-3 pt-1">
                <div className="skeleton h-5 w-2/3 rounded" />
                <div className="skeleton h-4 w-1/3 rounded" />
                <div className="skeleton h-10 w-full rounded" />
                <div className="skeleton h-8 w-1/2 rounded" />
              </div>
            </div>
          ))}
        </div>
      ) : items.length ? (
        <>
          <div className="mb-3 flex items-center justify-between text-xs text-ink-500">
            <span>{total} series in this view</span>
            <span className="inline-flex items-center gap-1"><Clock3 size={13} /> State updates when you read</span>
          </div>
          <div className={`grid gap-3 transition-opacity duration-200 lg:grid-cols-2 ${refreshing ? 'opacity-70' : 'opacity-100'}`}>
            {items.map((item) => <SmartLibraryCard key={item.series_id} item={item} />)}
          </div>
          {hasMore && (
            <div className="mt-6 text-center">
              <button
                type="button"
                disabled={loadingMore || refreshing}
                onClick={() => void load(nextOffsetRef.current, true)}
                className="rounded-xl border border-ink-700 bg-ink-900 px-5 py-2.5 text-sm font-medium text-ink-300 hover:border-ink-600 hover:text-ink-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </>
      ) : libraryKnown ? (
        <EmptyState title={emptyCopy.title} body={emptyCopy.body} />
      ) : (
        <div className="rounded-2xl border border-dashed border-amber-800/60 bg-amber-950/15 px-5 py-12 text-center">
          <p className="font-display text-lg font-semibold text-ink-200">Library data is unavailable</p>
          <p className="mx-auto mt-2 max-w-md text-sm text-ink-500">Retry when the personal library service is reachable. No empty-state counts are being inferred.</p>
        </div>
      )}
    </div>
  );
}
