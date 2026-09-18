import { Suspense, lazy, useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, ArrowUp, BookOpen, Library, CheckCircle2 } from 'lucide-react';
import { api, apiErrorMessage, apiErrorStatus, type Page, type ReaderData } from '../api/client';
import ProtectedPage from '../reader/ProtectedPage';
import { runtimeConfig } from '../config/runtime';
import { useAuth } from '../hooks/useAuth';
import { useReading } from '../reading/useReading';
import { completionEvidence } from '../reading/model';
import { ReadingVisit } from '../reading/visit';

const CommentSection = lazy(() => import('../components/CommentSection'));

function syncPauseMessage(code: string | null) {
  if (code === 'authentication_required') return 'Sign in again to save this reading position.';
  if (code === 'request_404') return 'This chapter is no longer available.';
  if (code === 'request_400' || code === 'request_422' || code === 'invalid_response') return 'This reading position needs review.';
  return 'Your reading position changed elsewhere. Choose which position to keep.';
}

function LazyImage({
  page,
  chapterToken,
  refreshChapterToken,
  alt,
  onLoaded,
}: {
  page: Page;
  chapterToken: string;
  refreshChapterToken: () => Promise<string>;
  alt: string;
  onLoaded: (page: number) => void;
}) {
  const [visible, setVisible] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const refreshAttemptedRef = useRef(false);

  useEffect(() => {
    setLoaded(false);
    refreshAttemptedRef.current = false;
  }, [page.image_path]);

  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect(); } },
      { rootMargin: '160px 0px' }
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  const refreshGrant = async () => {
    if (refreshing || refreshAttemptedRef.current) return;
    refreshAttemptedRef.current = true;
    setRefreshing(true);
    try {
      await refreshChapterToken();
    } finally {
      setRefreshing(false);
    }
  };

  const ratio = page.width && page.height ? `${page.width}/${page.height}` : undefined;

  return (
    <div
      ref={ref}
      className="w-full flex justify-center bg-ink-950"
      style={ratio ? { aspectRatio: ratio } : undefined}
    >
      {!visible ? (
        <div className="skeleton w-full" style={ratio ? undefined : { height: 400 }} />
      ) : (
        <div className="relative w-full">
          {!loaded && <div className="skeleton absolute inset-0" />}
          <img
            src={`/images/${page.image_path}?token=${encodeURIComponent(chapterToken)}`}
            alt={alt}
            loading="lazy"
            decoding="async"
            onLoad={() => { setLoaded(true); onLoaded(page.page_number); }}
            onError={() => { void refreshGrant(); }}
            className={`w-full transition-opacity duration-300 ${loaded ? 'opacity-100' : 'opacity-0'}`}
          />
        </div>
      )}
    </div>
  );
}

export default function Reader() {
  const { seriesSlug, chapterSlug } = useParams<{ seriesSlug: string; chapterSlug: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [data, setData] = useState<ReaderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showTopPrompt, setShowTopPrompt] = useState(false);
  const [activePage, setActivePage] = useState(1);
  const [chapterToken, setChapterToken] = useState("");
  const [loadError, setLoadError] = useState('');
  const [commentsVisible, setCommentsVisible] = useState(false);
  const chapterTokenRefreshRef = useRef<Promise<string> | null>(null);
  const commentsSentinelRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const chapterEndRef = useRef<HTMLDivElement>(null);
  const chapterEndReachedRef = useRef(false);
  const topPromptTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const currentPageRef = useRef(1);
  const { repository } = useReading(data?.series_id);
  const readingRecordRef = useRef<string | null>(null);
  const loadedPagesRef = useRef(new Set<number>());
  const recordSnapshotRef = useRef<() => void>(() => {});
  const readingVisitRef = useRef<ReadingVisit | null>(null);
  const openAttemptRef = useRef<{ key: string; id: string } | null>(null);

  const manifestRequestRef = useRef(0);

  const loadManifest = useCallback(async () => {
    if (!seriesSlug || !chapterSlug) return;
    const requestId = ++manifestRequestRef.current;
    setLoading(true);
    setLoadError('');
    setCommentsVisible(false);
    // Never leave the previous chapter visible while a new route is loading.
    setData(null);
    setChapterToken("");
    try {
      const d = await api.getReader(seriesSlug, chapterSlug);
      if (requestId !== manifestRequestRef.current) return;
      const normalized = d.chapter_encoding_seed
        ? {
            ...d,
            pages: d.pages.map((page) => ({
              ...page,
              encoding_seed: page.encoding_seed || d.chapter_encoding_seed || null,
            })),
          }
        : d;
      setData(normalized);
      setChapterToken(d.chapter_token || "");
      setActivePage(1);
    } catch (error) {
      if (requestId !== manifestRequestRef.current) return;
      setLoadError(
        apiErrorStatus(error) === 404
          ? 'Chapter not found.'
          : apiErrorMessage(error, 'Reader temporarily unavailable. Please retry.')
      );
    } finally {
      if (requestId === manifestRequestRef.current) setLoading(false);
    }
  }, [seriesSlug, chapterSlug, user?.id]);

  useEffect(() => {
    void loadManifest();
    return () => { manifestRequestRef.current++; chapterTokenRefreshRef.current = null; };
  }, [loadManifest]);

  const refreshChapterToken = useCallback(async (): Promise<string> => {
    if (!seriesSlug || !chapterSlug) throw new Error("Chapter route is unavailable.");
    if (chapterTokenRefreshRef.current) return chapterTokenRefreshRef.current;

    const manifestGeneration = manifestRequestRef.current;
    const request = api.refreshChapterToken(seriesSlug, chapterSlug)
      .then((grant) => {
        if (manifestGeneration !== manifestRequestRef.current) throw new Error("Chapter changed");
        setChapterToken(grant.token);
        return grant.token;
      })
      .finally(() => {
        if (chapterTokenRefreshRef.current === request) chapterTokenRefreshRef.current = null;
      });
    chapterTokenRefreshRef.current = request;
    return request;
  }, [seriesSlug, chapterSlug]);


  useEffect(() => {
    if (!data || !seriesSlug || !chapterSlug || !repository) return;
    let cancelled = false;
    let restoreFrame = 0;
    loadedPagesRef.current.clear();
    chapterEndReachedRef.current = false;
    currentPageRef.current = 1;
    const visitKey = `${manifestRequestRef.current}:${repository.scope}:${data.chapter_id}`;
    const visit: ReadingVisit = new ReadingVisit({ repository,
      id: openAttemptRef.current?.key === visitKey ? openAttemptRef.current.id : undefined,
      target: { series_id: data.series_id, chapter_id: data.chapter_id,
        series_slug: seriesSlug, chapter_slug: chapterSlug, page_count: data.page_count },
      read: repository.account() === null ? undefined : () => api.getProgress(repository.account()!, seriesSlug, chapterSlug),
      restore: position => {
        if (cancelled) return;
        currentPageRef.current = position.last_page;
        setActivePage(position.last_page);
        const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        window.scrollTo({ top: position.scroll_position * maxScroll, behavior: 'instant' });
        repository.checkpoint(visit.id, position.last_page, position.scroll_position, 0);
      },
    });
    openAttemptRef.current = { key: visitKey, id: visit.id };
    readingVisitRef.current = visit;
    readingRecordRef.current = visit.id;
    const onInteraction = () => visit.interact();
    window.addEventListener('wheel', onInteraction, { passive: true });
    window.addEventListener('touchstart', onInteraction, { passive: true });
    window.addEventListener('pointerdown', onInteraction, { passive: true });
    window.addEventListener('keydown', onInteraction);
    void visit.ready.then(() => {
      if (!cancelled) restoreFrame = requestAnimationFrame(() => {
        visit.restoreWhenReady();
        void repository.flush(true);
      });
      else void repository.flush(true);
    });
    return () => {
      recordSnapshotRef.current();
      visit.close();
      cancelled = true;
      cancelAnimationFrame(restoreFrame);
      window.removeEventListener('wheel', onInteraction);
      window.removeEventListener('touchstart', onInteraction);
      window.removeEventListener('pointerdown', onInteraction);
      window.removeEventListener('keydown', onInteraction);
      readingVisitRef.current = null;
      readingRecordRef.current = null;
    };
  }, [data, seriesSlug, chapterSlug, user?.id, repository]);

  const mediaChapterRef = useRef(data?.chapter_id);
  mediaChapterRef.current = data?.chapter_id;
  const mediaLoaded = useCallback((page: number) => {
    if (mediaChapterRef.current !== data?.chapter_id) return;
    loadedPagesRef.current.add(page);
    recordSnapshotRef.current();
  }, [data?.chapter_id]);

  useEffect(() => {
    if (!data || !seriesSlug || !chapterSlug || !repository) return;
    const snapshot = () => {
      const id = readingRecordRef.current;
      if (!id) return;
      const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      const completed = completionEvidence(chapterEndReachedRef.current, data.pages.map(p => p.page_number), loadedPagesRef.current, data.page_count);
      const previouslyCompleted = repository.records().find(r => r.id === id)?.completed_page || 0;
      readingVisitRef.current?.capture(currentPageRef.current, window.scrollY / maxScroll, completed);
      if (completed && !previouslyCompleted) void repository.flush();
    };
    recordSnapshotRef.current = snapshot;

    // Track the page crossing the viewport centre instead of requiring a
    // percentage of the whole image to be visible. Published webtoon segments
    // can be thousands of pixels tall, so a 25% intersection threshold may
    // never be reached on a normal phone/desktop viewport. If activePage stalls,
    // the protected-page fetch window stalls too and later pages appear blank.
    // A narrow centre band works for both short manga pages and very tall strips.
    const pageObserver = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting);
        if (visible.length === 0) return;
        const viewportCenter = window.innerHeight / 2;
        visible.sort((a, b) => {
          const ac = (a.boundingClientRect.top + a.boundingClientRect.bottom) / 2;
          const bc = (b.boundingClientRect.top + b.boundingClientRect.bottom) / 2;
          return Math.abs(ac - viewportCenter) - Math.abs(bc - viewportCenter);
        });
        const page = Number((visible[0].target as HTMLElement).dataset.page ?? '1');
        if (Number.isFinite(page) && page > 0 && page !== currentPageRef.current) {
          currentPageRef.current = page;
          setActivePage(page);
          snapshot();
        }
      },
      { rootMargin: '-45% 0px -45% 0px', threshold: 0 }
    );

    document.querySelectorAll<HTMLElement>('[data-page]').forEach((element) => {
      pageObserver.observe(element);
    });

    const endObserver = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) chapterEndReachedRef.current = true;
      snapshot();
    }, { threshold: 0.5 });
    if (chapterEndRef.current) endObserver.observe(chapterEndRef.current);
    const onScroll = () => { readingVisitRef.current?.interact(); snapshot(); };
    const onPageHide = () => { snapshot(); void repository.flush(); };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('pagehide', onPageHide);
    return () => {
      snapshot();
      void repository.flush();
      recordSnapshotRef.current = () => {};
      pageObserver.disconnect();
      endObserver.disconnect();
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('pagehide', onPageHide);
    };
  }, [data, seriesSlug, chapterSlug, repository]);


  const showTopPromptForTwoSeconds = useCallback(() => {
    setShowTopPrompt(true);
    if (topPromptTimerRef.current) clearTimeout(topPromptTimerRef.current);
    topPromptTimerRef.current = setTimeout(() => setShowTopPrompt(false), 2000);
  }, []);

  useEffect(() => () => {
    if (topPromptTimerRef.current) clearTimeout(topPromptTimerRef.current);
  }, []);

  const goToChapter = useCallback((slug: string | undefined) => {
    if (slug && seriesSlug) { recordSnapshotRef.current(); void repository?.flush(); navigate(`/read/${seriesSlug}/${slug}`); }
  }, [navigate, seriesSlug, repository]);

  useEffect(() => {
    if (!data) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        goToChapter(data.prev_chapter?.slug);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        goToChapter(data.next_chapter?.slug);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [data, goToChapter]);

  useEffect(() => {
    if (!data) return;
    const handleTouchStart = (event: TouchEvent) => {
      const touch = event.changedTouches[0];
      touchStartRef.current = { x: touch.clientX, y: touch.clientY };
    };
    const handleTouchEnd = (event: TouchEvent) => {
      const start = touchStartRef.current;
      touchStartRef.current = null;
      if (!start) return;
      const touch = event.changedTouches[0];
      const deltaX = touch.clientX - start.x;
      const deltaY = touch.clientY - start.y;
      if (Math.abs(deltaX) < 60 || Math.abs(deltaX) <= Math.abs(deltaY)) return;
      if (deltaX < 0) goToChapter(data.prev_chapter?.slug);
      else goToChapter(data.next_chapter?.slug);
    };

    window.addEventListener('touchstart', handleTouchStart, { passive: true });
    window.addEventListener('touchend', handleTouchEnd, { passive: true });
    return () => {
      window.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('touchend', handleTouchEnd);
    };
  }, [data, goToChapter]);

  useEffect(() => {
    if (!data || commentsVisible || !commentsSentinelRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setCommentsVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '800px 0px' },
    );
    observer.observe(commentsSentinelRef.current);
    return () => observer.disconnect();
  }, [data, commentsVisible]);

  if (loading) {
    return (
      <div className="min-h-screen bg-ink-950 flex items-center justify-center">
        <div className="skeleton w-full max-w-2xl" style={{ height: 600 }} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-ink-950 flex flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-ink-400">{loadError || 'Chapter unavailable'}</p>
        <button type="button" onClick={() => void loadManifest()} className="text-brand-400 hover:underline">Retry</button>
      </div>
    );
  }

  const readingRecord = repository?.records().find(r => r.id === readingRecordRef.current);
  const pausedRecord = repository?.records().filter(r => r.target.series_id === data.series_id && r.paused).sort((a, b) => a.created - b.created || a.id.localeCompare(b.id))[0];
  const syncStatus = repository?.storageError || (!readingRecord ? 'Preparing reading sync…' : pausedRecord ? `Sync paused. ${syncPauseMessage(pausedRecord.paused)}` : readingRecord.command || readingRecord.dirty ? repository?.hasVolatile() ? 'Saving locally' : user && navigator.onLine ? 'Saving' : 'Saved on this device' : user ? 'Reading synced' : 'Saved on this device');
  const activePageIndex = Math.max(
    0,
    data.pages.findIndex((candidate) => candidate.page_number === activePage),
  );

  return (
    <div className="min-h-screen min-w-0 max-w-full overflow-x-clip bg-ink-950">
      <div className="sticky top-14 z-40 min-w-0 border-b border-ink-800 bg-ink-900/95 px-3 py-3 backdrop-blur sm:px-4">
        <div className="flex items-center justify-between gap-3">
          <Link to={`/series/${seriesSlug}`} aria-label="Back to series" title="Back to series" className="flex min-w-0 shrink items-center gap-2 text-sm text-ink-300 transition-colors hover:text-ink-100">
            <BookOpen size={20} className="shrink-0" />
            <span className="hidden truncate sm:inline">{data.series_title}</span>
          </Link>
          <div className="min-w-0 text-right">
            <span className="block truncate text-sm font-medium text-ink-300">Ch. {data.chapter_number}{data.chapter_title ? ` — ${data.chapter_title}` : ''}</span>
            <span className="text-[10px] text-ink-500">Page {Math.min(activePage, data.page_count)} / {data.page_count}</span>
          </div>
        </div>
        <div className="absolute inset-x-0 bottom-0 h-0.5 bg-ink-800">
          <div className="h-full bg-brand-500 transition-[width] duration-200" style={{ width: `${Math.min(100, Math.max(0, (activePage / Math.max(1, data.page_count)) * 100))}%` }} />
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-3 sm:px-4 py-3 sm:py-4 grid grid-cols-3 items-center gap-2 sm:gap-4 border-b border-ink-900">
        {data.prev_chapter ? (
          <button onClick={() => goToChapter(data.prev_chapter?.slug)} className="min-w-0 flex items-center justify-center gap-1 sm:gap-2 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-xs sm:text-sm">
            <ArrowLeft size={18} className="shrink-0" /> <span className="hidden sm:inline">Prev Ch.</span><span className="sm:hidden">Prev</span>
          </button>
        ) : <div />}
        <Link to={`/series/${seriesSlug}`} className="min-w-0 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-center text-xs sm:text-sm"><span className="hidden sm:inline">Chapter list</span><span className="sm:hidden">List</span></Link>
        {data.next_chapter ? (
          <button onClick={() => goToChapter(data.next_chapter?.slug)} className="min-w-0 flex items-center justify-center gap-1 sm:gap-2 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-xs sm:text-sm">
            <span className="hidden sm:inline">Next Ch.</span><span className="sm:hidden">Next</span> <ArrowRight size={18} className="shrink-0" />
          </button>
        ) : <div />}
      </div>

      <div className="mx-auto max-w-2xl px-4 py-2 text-xs text-ink-400" role="status">
        {syncStatus}
        {pausedRecord && <button className="ml-3 text-brand-400" onClick={() => {
          if (window.confirm('Discard this unsynced reading intent and reload the server position?')) {
            void repository?.discard(pausedRecord.id).then(() => window.location.reload());
          }
        }}>Use server position</button>}
      </div>
      <div ref={containerRef} onClick={showTopPromptForTwoSeconds} className="max-w-2xl mx-auto cursor-pointer">
        {data.pages.map((page, pageIndex) => {
          const protectedPage = page.encoding_version === 4;
          // Windows are index-based, not page-number based. This keeps lazy
          // loading correct even if imported legacy data has page-number gaps.
          const inFetchWindow =
            pageIndex >= activePageIndex - runtimeConfig.readerFetchBehind &&
            pageIndex <= activePageIndex + runtimeConfig.readerFetchAhead;
          const inRetainWindow =
            pageIndex >= activePageIndex - runtimeConfig.readerRetainBehind &&
            pageIndex <= activePageIndex + runtimeConfig.readerRetainAhead;
          return (
            <div key={page.page_number} data-page={page.page_number} data-page-index={pageIndex}>
              {protectedPage ? (
                <ProtectedPage
                  page={page}
                  chapterToken={chapterToken}
                  refreshChapterToken={refreshChapterToken}
                  fetchEnabled={inFetchWindow}
                  retainDecoded={inRetainWindow}
                  onLoaded={mediaLoaded}
                  alt={`Page ${page.page_number}`}
                />
              ) : (
                <LazyImage
                  page={page}
                  chapterToken={chapterToken}
                  refreshChapterToken={refreshChapterToken}
                  onLoaded={mediaLoaded}
                  alt={`Page ${page.page_number}`}
                />
              )}
            </div>
          );
        })}
      </div>
      <div ref={chapterEndRef} className="h-px" aria-hidden="true" />

      <div className="max-w-2xl mx-auto px-3 sm:px-4 py-6 sm:py-8 grid grid-cols-3 items-center gap-2 sm:gap-4">
        {data.prev_chapter ? (
          <button onClick={() => goToChapter(data.prev_chapter?.slug)} className="min-w-0 flex items-center justify-center gap-1 sm:gap-2 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-xs sm:text-sm">
            <ArrowLeft size={18} className="shrink-0" /> <span className="hidden sm:inline">Prev Ch.</span><span className="sm:hidden">Prev</span>
          </button>
        ) : <div />}
        <Link to={`/series/${seriesSlug}`} className="min-w-0 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-center text-xs sm:text-sm"><span className="hidden sm:inline">Chapter list</span><span className="sm:hidden">List</span></Link>
        {data.next_chapter ? (
          <button onClick={() => goToChapter(data.next_chapter?.slug)} className="min-w-0 flex items-center justify-center gap-1 sm:gap-2 px-2 sm:px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 transition-colors text-xs sm:text-sm">
            <span className="hidden sm:inline">Next Ch.</span><span className="sm:hidden">Next</span> <ArrowRight size={18} className="shrink-0" />
          </button>
        ) : <div />}
      </div>

      {!data.next_chapter && (
        <div className="mx-auto mb-6 max-w-2xl px-3 sm:px-4">
          <div className="rounded-2xl border border-brand-800/40 bg-brand-950/15 px-5 py-5 text-center">
            <CheckCircle2 size={24} className="mx-auto text-brand-400" />
            <p className="mt-2 font-display text-lg font-semibold text-ink-100">You're caught up</p>
            <p className="mt-1 text-sm text-ink-500">This is currently the newest available chapter in the series.</p>
            <div className="mt-4 flex flex-col justify-center gap-2 sm:flex-row">
              <Link to="/library" className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-500"><Library size={17} /> Back to Library</Link>
              <Link to={`/series/${seriesSlug}`} className="inline-flex items-center justify-center gap-2 rounded-xl bg-ink-800 px-4 py-2.5 text-sm font-medium text-ink-200 hover:bg-ink-700"><BookOpen size={17} /> Series page</Link>
            </div>
          </div>
        </div>
      )}

      {showTopPrompt && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            setShowTopPrompt(false);
          }}
          className="fixed bottom-8 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2 rounded-full bg-brand-600 px-4 py-3 text-white shadow-lg animate-fade-in hover:bg-brand-500 transition-colors"
          aria-label="Go to first page"
        >
          <ArrowUp size={18} />
          <span className="text-sm font-medium">First page</span>
        </button>
      )}

      <div ref={commentsSentinelRef} className="min-w-0 max-w-3xl mx-auto px-3 sm:px-4 pb-12 min-h-24">
        {commentsVisible ? (
          <Suspense fallback={<div className="skeleton h-28 w-full" />}>
            <CommentSection seriesId={data.series_id} chapterId={data.chapter_id} />
          </Suspense>
        ) : null}
      </div>
    </div>
  );
}
