import { seriesReadingAction } from '../reading/model';
import { useReading } from '../reading/useReading';
import { READING_CONFIRMED_EVENT } from '../reading/browser';
import { lazy, Suspense, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { Bookmark, BookmarkCheck, Bell, BellOff, ArrowLeft, Trash2, Upload, Download, Loader2, FileArchive, X, Play, Search, Star, Users, History } from 'lucide-react';
import { api, apiErrorMessage, apiErrorStatus, type Series, type Chapter, type SeriesSocialMetrics, type SeriesReadingState } from '../api/client';
import { kebabCase } from '../utils/slug';
import { useAuth } from '../hooks/useAuth';

const CHAPTER_LIMIT = 20;
const CommentSection = lazy(() => import('../components/CommentSection'));

const normalizeChapterNumberSearch = (value: string): string => {
  const numeric = value.replace(/[^0-9.]/g, '');
  const [whole, ...fractionParts] = numeric.split('.');
  return fractionParts.length > 0
    ? `${whole}.${fractionParts.join('')}`
    : whole;
};

export default function SeriesDetail() {
  const { slug } = useParams<{ slug: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [series, setSeries] = useState<Series | null>(null);
  const [loading, setLoading] = useState(true);
  const [bookmarked, setBookmarked] = useState<boolean | null>(null);
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [chapterOffset, setChapterOffset] = useState(0);
  const [chapterReloadKey, setChapterReloadKey] = useState(0);
  const [chapterSearch, setChapterSearch] = useState('');
  const [chapterSearchQuery, setChapterSearchQuery] = useState('');
  const [chapterDownloadBusy, setChapterDownloadBusy] = useState<string | null>(null);
  const [socialMetrics, setSocialMetrics] = useState<SeriesSocialMetrics | null>(null);
  const [socialMetricsError, setSocialMetricsError] = useState('');
  const [readingState, setReadingState] = useState<SeriesReadingState | null>(null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [ratingError, setRatingError] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [uploadChapterSlug, setUploadChapterSlug] = useState('');
  const [uploadChapterNumber, setUploadChapterNumber] = useState(1);
  const [uploadChapterTitle, setUploadChapterTitle] = useState('');
  const [uploadSlugTouched, setUploadSlugTouched] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadFirstImage, setUploadFirstImage] = useState<File | null>(null);
  const [uploadLastImage, setUploadLastImage] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadResult, setUploadResult] = useState<{ page_count: number; total_size_bytes: number } | null>(null);
  const [loadError, setLoadError] = useState('');
  const [chapterDeleteNotice, setChapterDeleteNotice] = useState('');
  const [chapterDeleteBusyId, setChapterDeleteBusyId] = useState<string | null>(null);
  const [relationshipError, setRelationshipError] = useState('');
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const loadRequestRef = useRef(0);
  const relationshipMutationRef = useRef(0);
  const socialMetricsRequestRef = useRef(0);
  const relationshipIdentityRef = useRef('');
  relationshipIdentityRef.current = `${user?.id ?? 'guest'}:${series?.id ?? ''}`;
  const isAdmin = user?.role === 'admin';

  const loadSeries = useCallback(async () => {
    if (!slug) return;
    const requestId = ++loadRequestRef.current;
    setLoading(true);
    setLoadError('');
    // Do not keep a different route's series visible if navigation races with
    // a failed request. Same-series pagination may retain its last snapshot.
    setSeries((current) => current?.slug === slug ? current : null);
    try {
      const params = new URLSearchParams({ chapter_offset: String(chapterOffset), chapter_limit: String(CHAPTER_LIMIT) });
      if (chapterSearchQuery) params.set('chapter_search', chapterSearchQuery);
      const data = await api.getSeries(slug, `?${params.toString()}`);
      if (requestId !== loadRequestRef.current) return;
      setSeries(data);
      setLoadError('');
    } catch (error) {
      if (requestId !== loadRequestRef.current) return;
      if (apiErrorStatus(error) === 404) {
        setSeries(null);
        setLoadError('Series not found.');
      } else {
        setLoadError(apiErrorMessage(error, 'Series refresh failed. Showing the last successful data when available.'));
      }
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [slug, chapterOffset, chapterReloadKey, chapterSearchQuery]);

  useEffect(() => { loadSeries(); }, [loadSeries]);

  useEffect(() => {
    relationshipMutationRef.current++;
    socialMetricsRequestRef.current++;
    setRelationshipBusy(false);
  }, [user?.id, series?.id]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const query = chapterSearch.trim();
      setChapterOffset(0);
      setChapterSearchQuery(query);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [chapterSearch]);

  const filteredChapters = useMemo(() => {
    const chapters = series?.chapters || [];
    const query = chapterSearch.trim();
    if (!query) return chapters;
    return chapters.filter((chapter) => String(chapter.chapter_number).includes(query));
  }, [series?.chapters, chapterSearch]);

  const refreshSocialMetrics = useCallback(async () => {
    if (!series) return;
    const identity = relationshipIdentityRef.current;
    const requestId = ++socialMetricsRequestRef.current;
    setSocialMetricsError('');
    try {
      const metrics = user
        ? await api.seriesViewerState(series.id)
        : await api.seriesSocialMetrics(series.id);
      if (requestId !== socialMetricsRequestRef.current || identity !== relationshipIdentityRef.current) return;
      setSocialMetrics(metrics);
      if (user) {
        setBookmarked(metrics.bookmarked);
        setSubscribed(metrics.subscribed);
      }
    } catch (err: any) {
      if (requestId !== socialMetricsRequestRef.current || identity !== relationshipIdentityRef.current) return;
      setSocialMetricsError('Social metrics are unavailable.');
      if (user) {
        setRatingError(
          err?.detail || err?.message || 'Unable to load rating metrics.'
        );
      }
    }
  }, [series?.id, user?.id]);

  useEffect(() => {
    if (!series) return;
    let cancelled = false;
    setRelationshipError('');
    setSocialMetricsError('');
    setSocialMetrics(null);
    setBookmarked(null);
    setSubscribed(null);

    // Aggregate series metrics are public and must remain visible to guests.
    // Personal bookmark/follow/rating state is fetched only when authenticated,
    // so anonymous display never depends on Redis session lookup.
    if (user) {
      void api.seriesViewerState(series.id)
        .then((state) => {
          if (cancelled) return;
          setSocialMetrics(state);
          setSocialMetricsError('');
          setBookmarked(state.bookmarked);
          setSubscribed(state.subscribed);
        })
        .catch(() => {
          if (cancelled) return;
          setBookmarked(null);
          setSubscribed(null);
          setRelationshipError('Could not refresh bookmark/follow state. Retry before changing it.');
          void api.seriesSocialMetrics(series.id)
            .then((metrics) => {
              if (cancelled) return;
              setSocialMetrics(metrics);
              setSocialMetricsError('');
            })
            .catch(() => { if (!cancelled) setSocialMetricsError('Social metrics are unavailable.'); });
        });


    } else {
      setBookmarked(null);
      setSubscribed(null);
      setReadingState(null);
      void api.seriesSocialMetrics(series.id)
        .then((metrics) => {
          if (cancelled) return;
          setSocialMetrics(metrics);
          setSocialMetricsError('');
        })
        .catch(() => {
          if (cancelled) return;
          setSocialMetrics(null);
          setSocialMetricsError('Social metrics are unavailable.');
        });
    }

    return () => { cancelled = true; };
  }, [user, series?.id, series?.slug]);

  useEffect(() => {
    let generation = 0;
    let cancelled = false;
    setReadingState(null);
    const refresh = () => {
      if (!user || !series) return;
      const request = ++generation;
      void api.getSeriesReadingState(series.slug).then(state => {
        if (!cancelled && request === generation) setReadingState(state);
      }).catch(() => {});
    };
    refresh();
    window.addEventListener(READING_CONFIRMED_EVENT, refresh);
    return () => { cancelled = true; window.removeEventListener(READING_CONFIRMED_EVENT, refresh); };
  }, [user?.id, series?.id, series?.slug]);

  const { pending: pendingReading, repository: readingRepository } = useReading(series?.id);
  const primaryReadingAction = seriesReadingAction(series?.slug || '', readingState, series?.first_chapter, pendingReading, readingRepository?.storageError);
  const readChapterIds = useMemo(
    () => new Set(readingState?.read_chapter_ids || []),
    [readingState?.read_chapter_ids],
  );

  const toggleBookmark = async () => {
    if (!series || bookmarked === null) return;
    if (relationshipBusy) return;
    const identity = relationshipIdentityRef.current;
    const requestId = ++relationshipMutationRef.current;
    setRelationshipBusy(true);
    setRelationshipError('');
    try {
      if (bookmarked) await api.removeBookmark(series.id);
      else await api.addBookmark(series.id);
      if (requestId !== relationshipMutationRef.current || identity !== relationshipIdentityRef.current) return;
      setBookmarked(!bookmarked);
      await refreshSocialMetrics();
    } catch (error) {
      if (requestId !== relationshipMutationRef.current || identity !== relationshipIdentityRef.current) return;
      setRelationshipError(apiErrorMessage(error, 'Bookmark update failed. Please retry.'));
    } finally {
      if (requestId === relationshipMutationRef.current && identity === relationshipIdentityRef.current) setRelationshipBusy(false);
    }
  };

  const rateSeries = async (rating: number) => {
    if (!series) return;
    if (!user) {
      setRatingError('Sign in to rate this series.');
      return;
    }
    if (ratingBusy) return;

    setRatingBusy(true);
    setRatingError('');

    try {
      const metrics = await api.setSeriesRating(series.id, rating);
      setSocialMetrics(metrics);
    } catch (err: any) {
      setRatingError(
        err?.detail ||
          err?.message ||
          'Unable to save your rating. Please try again.'
      );
    } finally {
      setRatingBusy(false);
    }
  };

  const toggleSubscribe = async () => {
    if (!series || subscribed === null) return;
    if (relationshipBusy) return;
    const identity = relationshipIdentityRef.current;
    const requestId = ++relationshipMutationRef.current;
    setRelationshipBusy(true);
    setRelationshipError('');
    try {
      if (subscribed) await api.unsubscribe(series.id);
      else await api.subscribe(series.id);
      if (requestId !== relationshipMutationRef.current || identity !== relationshipIdentityRef.current) return;
      setSubscribed(!subscribed);
      await refreshSocialMetrics();
    } catch (error) {
      if (requestId !== relationshipMutationRef.current || identity !== relationshipIdentityRef.current) return;
      setRelationshipError(apiErrorMessage(error, 'Subscription update failed. Please retry.'));
    } finally {
      if (requestId === relationshipMutationRef.current && identity === relationshipIdentityRef.current) setRelationshipBusy(false);
    }
  };

  const handleDownloadChapter = async (chapter: Chapter) => {
    if (chapterDownloadBusy) return;
    setChapterDownloadBusy(chapter.id);
    try {
      await api.downloadChapterExport(chapter.id, 'stored');
    } catch (err: any) {
      window.alert(err?.detail || err?.message || 'Chapter export failed.');
    } finally {
      setChapterDownloadBusy(null);
    }
  };

  const handleDeleteChapter = async (chapter: Chapter) => {
    if (!series || chapterDeleteBusyId) return;
    if (!window.confirm(`Delete chapter ${chapter.chapter_number}?`)) return;
    setChapterDeleteBusyId(chapter.id);
    setLoadError('');
    try {
      // Catalog deletion owns the complete lifecycle. Storage/cache cleanup is
      // durably queued by the backend; the UI must not perform a second delete.
      const result = await api.deleteChapter(series.id, chapter.id);
      setChapterDeleteNotice(`Chapter removed from Catalog. Storage cleanup is ${result.storage_cleanup} (job ${result.job_id}).`);
      setSeries(prev => prev ? {
        ...prev,
        chapters: (prev.chapters || []).filter(c => c.id !== chapter.id),
      } : null);
      if ((series.chapters || []).length === 1 && chapterOffset > 0) {
        setChapterOffset(prev => prev - CHAPTER_LIMIT);
      } else {
        setChapterReloadKey(k => k + 1);
      }
    } catch (error) {
      setLoadError(apiErrorMessage(error, 'Chapter deletion failed. Please retry.'));
    } finally {
      setChapterDeleteBusyId(null);
    }
  };

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!series || !uploadChapterSlug || !uploadFile) { setUploadError('Chapter slug and file are required.'); return; }
    setUploading(true);
    setUploadError('');
    setUploadResult(null);
    try {
      const res = await api.uploadChapter(series.slug, uploadChapterSlug, uploadFile, parseFloat(String(uploadChapterNumber)) || 1, uploadChapterTitle || null, uploadFirstImage, uploadLastImage);
      setUploadResult({ page_count: res.page_count, total_size_bytes: res.total_size_bytes });
      setUploadChapterSlug('');
      setUploadChapterNumber(1);
      setUploadChapterTitle('');
      setUploadFile(null);
      setUploadFirstImage(null);
      setUploadLastImage(null);
      setUploadSlugTouched(false);
      setChapterReloadKey(k => k + 1);
      loadSeries();
    } catch (err: any) {
      setUploadError(err?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return (
      <div className="w-full min-w-0 max-w-5xl mx-auto px-3 sm:px-4 py-6 sm:py-8">
        <div className="skeleton h-8 w-32 rounded mb-6" />
        <div className="flex flex-col sm:flex-row gap-6">
          <div className="skeleton w-40 sm:w-48 h-60 sm:h-72 self-center sm:self-start rounded-xl" />
          <div className="flex-1 min-w-0 space-y-4">
            <div className="skeleton h-8 w-2/3 rounded" />
            <div className="skeleton h-4 w-1/3 rounded" />
            <div className="skeleton h-20 w-full rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (!series) {
    return (
      <div className="w-full min-w-0 max-w-5xl mx-auto px-3 sm:px-4 py-20 text-center">
        <p className="text-ink-400 text-lg">{loadError || 'Series unavailable'}</p>
        <button type="button" onClick={() => void loadSeries()} className="mt-3 mr-3 text-brand-400 hover:underline">Retry</button>
        <Link to="/" className="text-brand-400 hover:underline mt-2 inline-block">Back to catalog</Link>
      </div>
    );
  }

  return (
    <div className="w-full min-w-0 max-w-5xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <Link to="/" className="inline-flex items-center gap-2 text-ink-400 hover:text-ink-100 mb-6 transition-colors">
        <ArrowLeft size={18} /> Back
      </Link>

      {loadError && (
        <div className="mb-4 rounded-xl border border-amber-700/50 bg-amber-950/25 px-4 py-3 text-sm text-amber-200">
          {loadError} <button type="button" onClick={() => void loadSeries()} className="ml-2 underline">Retry</button>
        </div>
      )}
      {chapterDeleteNotice && (
        <div className="mb-4 rounded-xl border border-amber-700/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
          {chapterDeleteNotice}
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-6 mb-8">
        <div className="w-40 h-60 sm:w-48 sm:h-72 self-center sm:self-start rounded-xl overflow-hidden bg-ink-800 flex-shrink-0">
          {series.cover_image_path ? (
            <img src={`/images/${series.cover_image_path}`} alt={series.title} className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-ink-700 to-ink-800">
              <span className="text-4xl font-display font-bold text-ink-500">{series.title[0]}</span>
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <h1 className="mreader-break-anywhere font-display text-2xl sm:text-3xl font-bold mb-2">{series.title}</h1>
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <span className={`text-xs font-medium px-2 py-1 rounded-full ${
              series.status === 'ongoing' ? 'bg-green-600/80' :
              series.status === 'completed' ? 'bg-blue-600/80' : series.status === 'cancelled' ? 'bg-red-600/80' : 'bg-yellow-600/80'
            }`}>{series.status}</span>
            {series.genres?.map(g => (
              <span key={g.id} className="max-w-full whitespace-normal break-words text-center text-xs px-2 py-1 rounded-full bg-ink-800 text-ink-300">{g.name}</span>
            ))}
          </div>
          {series.tags && series.tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {series.tags.map(t => (
                <span key={t.id} className="max-w-full whitespace-normal break-words text-center text-xs px-2 py-1 rounded-full bg-brand-600/20 text-brand-300 border border-brand-600/30">{t.name}</span>
              ))}
            </div>
          )}
          {series.description && <p className="mreader-break-anywhere text-ink-300 mb-4 leading-relaxed">{series.description}</p>}

          {primaryReadingAction && (
            <Link
              to={primaryReadingAction.href}
              className="mb-4 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-500"
            >
              <Play size={17} fill="currentColor" />
              {primaryReadingAction.label}
            </Link>
          )}

          {primaryReadingAction?.status && <p role="status" className="mb-4 text-sm text-amber-300">{primaryReadingAction.status}</p>}

          <div className="flex flex-wrap items-center gap-4 mb-4 rounded-xl border border-ink-800 bg-ink-900/60 px-4 py-3">
            <div className="flex items-center gap-2">
              <Star size={18} className="text-amber-400" fill="currentColor" />
              <span className="font-semibold">{socialMetrics?.rating_average?.toFixed(1) ?? '—'}</span>
              <span className="text-xs text-ink-500">({socialMetrics?.rating_count ?? '—'} ratings)</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-ink-300">
              <Bookmark size={16} className="text-brand-400" /> {socialMetrics?.bookmark_count ?? '—'} bookmarks
            </div>
            <div className="flex items-center gap-2 text-sm text-ink-300">
              <Users size={16} className="text-brand-400" /> {socialMetrics?.subscription_count ?? '—'} followers
            </div>
            {user && (
              <div className="w-full sm:w-auto sm:ml-auto flex items-center justify-start sm:justify-end gap-1" title="Your rating">
                {[1,2,3,4,5].map(value => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => void rateSeries(value)}
                    disabled={ratingBusy}
                    className="p-1 hover:scale-110 transition-transform disabled:opacity-50"
                    aria-label={`Rate ${value} stars`}
                    title={`Rate ${value} star${value === 1 ? '' : 's'}`}
                  >
                    <Star
                      size={18}
                      className={value <= (socialMetrics?.user_rating ?? 0) ? 'text-amber-400' : 'text-ink-600'}
                      fill={value <= (socialMetrics?.user_rating ?? 0) ? 'currentColor' : 'none'}
                    />
                  </button>
                ))}
              </div>
            )}
          </div>

          {user && (
            <div className="mb-3 text-xs text-ink-500">
              Your rating: {socialMetricsError ? 'unavailable' : socialMetrics ? (socialMetrics.user_rating ? `${socialMetrics.user_rating}/5` : 'not rated yet') : 'checking…'}
              {ratingBusy ? ' · saving…' : ''}
            </div>
          )}

          {socialMetricsError && (
            <div className="mb-3 rounded-lg border border-amber-800/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
              {socialMetricsError}
            </div>
          )}

          {ratingError && (
            <div className="mb-3 rounded-lg border border-red-800/60 bg-red-950/30 px-3 py-2 text-xs text-red-200">
              {ratingError}
            </div>
          )}

          {relationshipError && (
            <div className="mb-3 rounded-lg border border-amber-800/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
              {relationshipError}
            </div>
          )}

          {user && (
            <div className="flex flex-wrap gap-2 sm:gap-3">
              <button disabled={relationshipBusy || bookmarked === null} onClick={toggleBookmark} className="flex w-full sm:w-auto items-center justify-center gap-2 px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 transition-colors text-sm font-medium">
                {bookmarked ? <BookmarkCheck className="text-brand-400" size={18} /> : <Bookmark size={18} />}
                {bookmarked === null ? 'Checking bookmark…' : bookmarked ? 'Bookmarked' : 'Bookmark'}
              </button>
              <button disabled={relationshipBusy || subscribed === null} onClick={toggleSubscribe} className="flex w-full sm:w-auto items-center justify-center gap-2 px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 transition-colors text-sm font-medium">
                {subscribed ? <Bell className="text-brand-400" size={18} /> : <BellOff size={18} />}
                {subscribed === null ? 'Checking follow…' : subscribed ? 'Subscribed' : 'Subscribe'}
              </button>
              {isAdmin && (
                <button onClick={() => setShowUpload(!showUpload)} className="flex w-full sm:w-auto items-center justify-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white transition-colors text-sm font-medium">
                  <Upload size={18} /> Upload Chapter
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <h2 className="font-display text-xl font-bold mb-4">Chapters</h2>

      {isAdmin && showUpload && (
        <div className="min-w-0 bg-ink-900 border border-ink-800 rounded-xl p-4 sm:p-6 mb-6 animate-fade-in">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-lg font-bold">Upload New Chapter</h3>
            <button onClick={() => setShowUpload(false)} className="text-ink-400 hover:text-ink-100 transition-colors">
              <X size={18} />
            </button>
          </div>
          {uploadError && <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-2 rounded-lg text-sm mb-4">{uploadError}</div>}
          {uploadResult && (
            <div className="bg-green-900/30 border border-green-700/50 text-green-300 px-4 py-2 rounded-lg text-sm mb-4">
              Upload successful! {uploadResult.page_count} pages, {(uploadResult.total_size_bytes / 1024 / 1024).toFixed(1)} MB
            </div>
          )}
          <form onSubmit={handleUploadSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-ink-300 mb-1">Chapter Number</label>
                <input type="number" step="0.01" value={uploadChapterNumber} onChange={(e) => setUploadChapterNumber(parseFloat(e.target.value))} required className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm text-ink-300 mb-1">Chapter Slug</label>
                <input type="text" value={uploadChapterSlug} onChange={(e) => { setUploadSlugTouched(true); setUploadChapterSlug(e.target.value); }} required pattern="[a-z0-9-]+" placeholder="chapter-1" className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-sm text-ink-300 mb-1">Chapter Title (optional)</label>
              <input type="text" value={uploadChapterTitle} onChange={(e) => { const value=e.target.value; setUploadChapterTitle(value); if (!uploadSlugTouched || !uploadChapterSlug) setUploadChapterSlug(kebabCase(value)); }} className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none" />
            </div>
            <div>
              <label className="block text-sm text-ink-300 mb-1">ZIP/CBZ/PDF</label>
              <div className="min-w-0 border-2 border-dashed border-ink-700 rounded-xl p-4 sm:p-6 text-center hover:border-brand-500 transition-colors">
                <FileArchive size={28} className="mx-auto text-ink-500 mb-2" />
                <input type="file" accept=".zip,.cbz,.pdf,application/zip,application/x-zip-compressed,application/x-cbz,application/pdf" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} className="w-full max-w-full text-sm text-ink-400 file:mr-2 sm:file:mr-3 file:py-2 file:px-3 sm:file:px-4 file:rounded-lg file:border-0 file:bg-brand-600 file:text-white" />
                {uploadFile && <p className="mreader-break-anywhere text-ink-300 text-sm mt-2">{uploadFile.name}</p>}
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div><label className="block text-sm text-ink-300 mb-1">First page image (optional)</label><input type="file" accept="image/*" onChange={(e) => setUploadFirstImage(e.target.files?.[0] || null)} className="text-sm text-ink-400" /></div>
              <div><label className="block text-sm text-ink-300 mb-1">Last page image (optional)</label><input type="file" accept="image/*" onChange={(e) => setUploadLastImage(e.target.files?.[0] || null)} className="text-sm text-ink-400" /></div>
            </div>
            <button type="submit" disabled={uploading} className="w-full py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2">
              {uploading ? <><Loader2 className="animate-spin" size={18} /> Uploading...</> : <><Upload size={18} /> Upload & Publish</>}
            </button>
          </form>
        </div>
      )}
      <div className="relative mb-4">
        <Search size={17} className="absolute left-3 top-3 text-ink-500" />
        <input
          value={chapterSearch}
          onChange={(e) => setChapterSearch(normalizeChapterNumberSearch(e.target.value))}
          inputMode="decimal"
          autoComplete="off"
          aria-label="Search by chapter number"
          placeholder="Search chapter number…"
          className="w-full pl-10 pr-10 py-2.5 rounded-xl bg-ink-900 border border-ink-800 focus:border-brand-500 focus:outline-none"
        />
        {chapterSearch && <button onClick={() => setChapterSearch('')} className="absolute right-3 top-2.5 text-ink-500 hover:text-ink-100"><X size={17}/></button>}
      </div>
      {chapterSearch && <div className="text-xs text-ink-500 mb-3">Searching all published chapters by number: {chapterSearch}</div>}

      <div className="space-y-2">
        {filteredChapters.map((ch) => (
          <div key={ch.id} className={`flex min-w-0 items-start justify-between gap-2 rounded-lg border px-3 py-3 transition-colors sm:items-center sm:px-4 ${readChapterIds.has(ch.id) ? 'border-brand-700/40 bg-brand-950/15 hover:border-brand-600/50' : 'border-ink-800 bg-ink-900 hover:border-ink-700'}`}>
            <Link to={`/read/${series.slug}/${ch.slug}`} className="flex min-w-0 flex-1 flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-3">
              <span className={`shrink-0 text-sm font-mono sm:w-16 ${readChapterIds.has(ch.id) ? 'text-brand-300' : 'text-ink-400'}`}>Ch. {ch.chapter_number}</span>
              {ch.title && <span className={`mreader-break-anywhere min-w-0 text-sm ${readChapterIds.has(ch.id) ? 'text-ink-300' : 'text-ink-200'}`}>{ch.title}</span>}
              {pendingReading?.chapter_id === ch.id && <span className="text-xs text-amber-300">Local page {pendingReading.last_page} · {readingRepository?.storageError || pendingReading.status}</span>}
              {readChapterIds.has(ch.id) && <span className="inline-flex items-center gap-1 rounded-full bg-brand-600/15 px-2 py-0.5 text-[10px] font-medium text-brand-300"><History size={11} /> Read</span>}
              {isAdmin && ch.status !== 'published' && (
                <span className="text-xs text-yellow-500">({ch.status})</span>
              )}
            </Link>
            {isAdmin && (
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => void handleDownloadChapter(ch)}
                  disabled={chapterDownloadBusy === ch.id}
                  className="p-2 text-ink-500 hover:text-brand-400 disabled:opacity-50 transition-colors"
                  aria-label={`Download chapter ${ch.chapter_number} stored pages`}
                  title="Download stored chapter ZIP"
                >
                  {chapterDownloadBusy === ch.id ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
                </button>
                <button
                  onClick={() => handleDeleteChapter(ch)}
                  disabled={chapterDeleteBusyId === ch.id}
                  className="p-2 text-ink-500 hover:text-red-400 disabled:opacity-50 transition-colors"
                  aria-label={`Delete chapter ${ch.chapter_number}`}
                  title="Delete chapter"
                >
                  {chapterDeleteBusyId === ch.id ? <Loader2 className="animate-spin" size={16} /> : <Trash2 size={16} />}
                </button>
              </div>
            )}
          </div>
        ))}
              {chapterSearch && filteredChapters.length === 0 && (
          <div className="rounded-lg border border-ink-800 bg-ink-900 px-4 py-5 text-center text-sm text-ink-500">
            No published chapter numbers match {chapterSearch}.
          </div>
        )}
      </div>

      {((series.chapters?.length || 0) > 0 || chapterOffset > 0) && (
        <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-4 mt-6">
          <button
            onClick={() => { setChapterOffset(Math.max(0, chapterOffset - CHAPTER_LIMIT)); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            disabled={chapterOffset === 0}
            className="px-4 py-2 rounded-lg bg-ink-800 text-ink-200 disabled:opacity-40 hover:bg-ink-700 transition-colors text-sm"
          >Newer</button>
          <button
            onClick={() => { setChapterOffset(chapterOffset + CHAPTER_LIMIT); window.scrollTo({ top: 0, behavior: 'smooth' }); }}
            disabled={!series.chapter_has_more}
            className="px-4 py-2 rounded-lg bg-ink-800 text-ink-200 disabled:opacity-40 hover:bg-ink-700 transition-colors text-sm"
          >Older</button>
        </div>
      )}

      <section className="mt-10 border-t border-ink-800 pt-8" aria-label="Series discussion">
        <p className="mb-4 text-sm text-ink-500">General discussion for this series. Chapter discussions remain separate inside each reader chapter.</p>
        <Suspense fallback={<div className="skeleton h-32 w-full max-w-3xl rounded-xl" />}>
          <CommentSection seriesId={series.id} title="Series Discussion" />
        </Suspense>
      </section>
    </div>
  );
}
