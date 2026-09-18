import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Archive, CheckCircle2, Database, Download, HardDrive, Loader2, RefreshCw, RotateCcw, Unlock } from 'lucide-react';
import { api, apiErrorMessage, type Chapter, type LifecycleCleanupJob, type ScraperStagingHealth, type Series } from '../api/client';
import SearchableSeriesPicker, { type SeriesPickerOption } from '../components/SearchableSeriesPicker';

export default function AdminStorage() {
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [seriesSearch, setSeriesSearch] = useState('');
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [cleanupJobs, setCleanupJobs] = useState<LifecycleCleanupJob[]>([]);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupError, setCleanupError] = useState('');
  const [retryingCleanup, setRetryingCleanup] = useState<string | null>(null);
  const [stagingHealth, setStagingHealth] = useState<ScraperStagingHealth | null>(null);
  const [stagingHealthError, setStagingHealthError] = useState('');
  const [stagingHealthLoading, setStagingHealthLoading] = useState(false);
  const seriesRequestRef = useRef(0);

  const loadSeries = useCallback(async (search: string) => {
    const requestId = ++seriesRequestRef.current;
    setSeriesLoading(true);
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (search.trim()) params.set('search', search.trim());
      const data = await api.listSeries(`?${params.toString()}`);
      if (requestId !== seriesRequestRef.current) return;
      setSeriesList(data);
      setError('');
    } catch {
      if (requestId !== seriesRequestRef.current) return;
      setError('Failed to search series. Showing the last successful matches.');
    } finally {
      if (requestId === seriesRequestRef.current) setSeriesLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadSeries(seriesSearch), 250);
    return () => window.clearTimeout(timer);
  }, [loadSeries, seriesSearch]);

  useEffect(() => {
    if (!selectedSeries) {
      setChapters([]);
      return;
    }
    let cancelled = false;
    const load = async () => {
      setChapterLoading(true);
      setError('');
      try {
        const all: Chapter[] = [];
        let offset = 0;
        let hasMore = true;
        while (hasMore) {
          const detail = await api.getSeries(
            selectedSeries.slug,
            `?chapter_offset=${offset}&chapter_limit=100`,
          );
          const batch = detail.chapters || [];
          all.push(...batch);
          hasMore = Boolean(detail.chapter_has_more);
          offset += batch.length;
          if (!batch.length) break;
        }
        if (!cancelled) setChapters(all);
      } catch {
        if (!cancelled) setError('Failed to load chapters.');
      } finally {
        if (!cancelled) setChapterLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [selectedSeries]);

  const loadCleanupJobs = useCallback(async () => {
    setCleanupLoading(true);
    setCleanupError('');
    try {
      setCleanupJobs(await api.listLifecycleCleanupJobs('active', 50));
    } catch (err) {
      setCleanupError(apiErrorMessage(err, 'Failed to load lifecycle cleanup jobs.'));
    } finally {
      setCleanupLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCleanupJobs();
  }, [loadCleanupJobs]);

  const loadStagingHealth = useCallback(async () => {
    setStagingHealthLoading(true);
    setStagingHealthError('');
    try {
      setStagingHealth(await api.getScraperStagingHealth());
    } catch (err) {
      setStagingHealthError(apiErrorMessage(err, 'Failed to read scraper staging health.'));
    } finally {
      setStagingHealthLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStagingHealth();
  }, [loadStagingHealth]);

  const retryCleanup = async (jobId: string) => {
    setRetryingCleanup(jobId);
    setCleanupError('');
    try {
      await api.retryLifecycleCleanupJob(jobId);
      await loadCleanupJobs();
    } catch (err) {
      setCleanupError(apiErrorMessage(err, 'Failed to retry cleanup job.'));
    } finally {
      setRetryingCleanup(null);
    }
  };

  const cleanupSummary = useMemo(() => ({
    queued: cleanupJobs.filter((job) => job.status === 'queued').length,
    processing: cleanupJobs.filter((job) => job.status === 'processing').length,
    retry: cleanupJobs.filter((job) => job.status === 'retry').length,
    failed: cleanupJobs.filter((job) => job.status === 'failed').length,
  }), [cleanupJobs]);

  const pickerOptions = useMemo<SeriesPickerOption[]>(
    () => seriesList.map((item) => ({ id: item.id, title: item.title, slug: item.slug, subtitle: item.status })),
    [seriesList],
  );
  const selectedOption = useMemo<SeriesPickerOption | null>(
    () => selectedSeries ? { id: selectedSeries.id, title: selectedSeries.title, slug: selectedSeries.slug, subtitle: selectedSeries.status } : null,
    [selectedSeries],
  );

  const chooseSeries = (option: SeriesPickerOption | null) => {
    setSelectedSeries(option ? seriesList.find((item) => item.id === option.id) || null : null);
  };

  const download = async (chapter: Chapter, mode: 'stored' | 'decoded') => {
    const key = `${chapter.id}:${mode}`;
    setDownloading(key);
    setError('');
    try {
      await api.downloadChapterExport(chapter.id, mode);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Chapter export failed.');
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="w-full min-w-0 max-w-5xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex items-center justify-between gap-3 mb-6">
        <div>
          <Link to="/admin" className="text-ink-400 hover:text-ink-100 text-sm">Back to Admin</Link>
          <h1 className="font-display text-2xl sm:text-3xl font-bold mt-2">Chapter Storage Exports</h1>
          <p className="text-sm text-ink-400 mt-2">Download the converted pages exactly as stored, or create a readable decoded backup.</p>
        </div>
        <Database className="text-brand-400 shrink-0" size={30} />
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-3 rounded-lg mb-4 text-sm">{error}</div>}

      {cleanupError && <div className="bg-amber-900/25 border border-amber-700/50 text-amber-200 px-4 py-3 rounded-lg mb-4 text-sm">{cleanupError}</div>}
      {stagingHealthError && <div className="bg-red-900/25 border border-red-700/50 text-red-200 px-4 py-3 rounded-lg mb-4 text-sm">{stagingHealthError}</div>}

      <section className="bg-ink-900 border border-ink-800 rounded-xl p-4 mb-5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 font-medium text-ink-100">
              <HardDrive size={17} /> Scraper durable staging spool
            </div>
            <p className="text-xs text-ink-500 mt-1">All scraper processes must resolve the same host-mounted SSD spool before jobs are accepted.</p>
          </div>
          <button
            onClick={() => void loadStagingHealth()}
            disabled={stagingHealthLoading}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 text-sm"
          >
            <RefreshCw size={15} className={stagingHealthLoading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
        {stagingHealth && (
          <div className={`mt-4 rounded-lg border px-3 py-3 text-sm ${stagingHealth.healthy ? 'border-green-800/60 bg-green-950/25' : 'border-red-800/60 bg-red-950/25'}`}>
            <div className="flex items-center gap-2">
              {stagingHealth.healthy ? <CheckCircle2 size={16} className="text-green-400" /> : <AlertTriangle size={16} className="text-red-400" />}
              <span className={stagingHealth.healthy ? 'text-green-300' : 'text-red-300'}>{stagingHealth.healthy ? 'Shared staging volume is healthy' : 'Staging volume needs attention'}</span>
            </div>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-1 text-xs text-ink-400">
              <div className="break-all">Container root: <span className="text-ink-200">{stagingHealth.root}</span></div>
              <div>Storage backend: <span className="text-ink-200">{stagingHealth.storage_backend}</span></div>
              {stagingHealth.volume_name_hint && <div className="break-all">Docker volume: <span className="text-ink-200">{stagingHealth.volume_name_hint}</span></div>}
              <div>Writable: <span className="text-ink-200">{stagingHealth.writable ? 'yes' : 'no'}</span></div>
              <div>Volume mount visible: <span className="text-ink-200">{stagingHealth.mount_visible ? 'yes' : 'no'}</span></div>
              <div>Spool identity matches DB: <span className="text-ink-200">{stagingHealth.identity_matches ? 'yes' : 'no'}</span></div>
              <div>DB staged refs sampled: <span className="text-ink-200">{stagingHealth.reference_sample}</span></div>
              <div>Missing local refs: <span className={stagingHealth.reference_missing ? 'text-amber-300' : 'text-ink-200'}>{stagingHealth.reference_missing}</span></div>
              {stagingHealth.spool_id && <div className="sm:col-span-2 break-all">Spool ID: <span className="text-ink-200">{stagingHealth.spool_id}</span></div>}
              {stagingHealth.canonical?.last_service && <div className="sm:col-span-2">Last registered service: <span className="text-ink-200">{stagingHealth.canonical.last_service}</span></div>}
              {stagingHealth.reference_missing_examples?.length > 0 && (
                <div className="sm:col-span-2 break-all text-red-300">Missing staged-file example: {stagingHealth.reference_missing_examples[0]}</div>
              )}
            </div>
          </div>
        )}
      </section>

      <section className="bg-ink-900 border border-ink-800 rounded-xl p-4 mb-5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 font-medium text-ink-100">
              <Database size={17} /> Durable lifecycle cleanup
            </div>
            <p className="text-xs text-ink-500 mt-1">Queued storage cleanup is retryable and survives worker, database, NAS, and application restarts.</p>
          </div>
          <button
            onClick={() => void loadCleanupJobs()}
            disabled={cleanupLoading}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 text-sm"
          >
            <RefreshCw size={15} className={cleanupLoading ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-4 text-xs">
          <div className="rounded-lg bg-ink-950 border border-ink-800 px-3 py-2"><span className="text-ink-500">Queued</span><div className="text-lg text-ink-100 mt-1">{cleanupSummary.queued}</div></div>
          <div className="rounded-lg bg-ink-950 border border-ink-800 px-3 py-2"><span className="text-ink-500">Processing</span><div className="text-lg text-ink-100 mt-1">{cleanupSummary.processing}</div></div>
          <div className="rounded-lg bg-ink-950 border border-ink-800 px-3 py-2"><span className="text-ink-500">Retrying</span><div className="text-lg text-ink-100 mt-1">{cleanupSummary.retry}</div></div>
          <div className="rounded-lg bg-ink-950 border border-ink-800 px-3 py-2"><span className="text-ink-500">Failed</span><div className="text-lg text-ink-100 mt-1">{cleanupSummary.failed}</div></div>
        </div>

        {cleanupLoading && cleanupJobs.length === 0 ? (
          <div className="flex items-center gap-2 py-5 text-sm text-ink-400"><Loader2 className="animate-spin" size={16} /> Loading cleanup state…</div>
        ) : cleanupJobs.length === 0 ? (
          <div className="py-5 text-sm text-ink-500">No queued, retrying, processing, or failed cleanup jobs.</div>
        ) : (
          <div className="mt-4 border border-ink-800 rounded-lg overflow-hidden">
            {cleanupJobs.map((job) => (
              <div key={job.id} className="p-3 border-b border-ink-800 last:border-b-0">
                <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      {job.status === 'failed' && <AlertTriangle size={15} className="text-amber-400" />}
                      <span className="font-medium text-ink-200">{job.entity_type}</span>
                      <span className="px-2 py-0.5 rounded bg-ink-800 text-ink-400">{job.status}</span>
                      <span className="text-ink-500">attempt {job.attempts}/{job.max_attempts}</span>
                    </div>
                    <div className="text-xs text-ink-600 mt-1 break-all">{job.entity_id || job.id}</div>
                    {job.last_error && <div className="text-xs text-amber-300/90 mt-2 break-words">{job.last_error}</div>}
                  </div>
                  {(job.status === 'failed' || job.status === 'retry') && (
                    <button
                      onClick={() => void retryCleanup(job.id)}
                      disabled={Boolean(retryingCleanup)}
                      className="inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-amber-700/70 hover:bg-amber-600 disabled:opacity-50 text-white text-xs"
                    >
                      {retryingCleanup === job.id ? <Loader2 className="animate-spin" size={14} /> : <RotateCcw size={14} />}
                      Retry
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="bg-ink-900 border border-ink-800 rounded-xl p-4 mb-5">
        <SearchableSeriesPicker
          query={seriesSearch}
          onQueryChange={setSeriesSearch}
          options={pickerOptions}
          selected={selectedOption}
          onSelect={chooseSeries}
          loading={seriesLoading}
          placeholder="Search series by title or slug…"
          emptyText="No matching series."
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5 text-sm">
        <div className="bg-ink-900 border border-ink-800 rounded-xl p-4">
          <div className="flex items-center gap-2 font-medium text-ink-200"><Archive size={17} /> Stored ZIP</div>
          <p className="text-ink-400 mt-2">Exact WebP bytes from SeaweedFS. Protected pages remain scrambled. The private manifest includes their codec metadata and seeds.</p>
        </div>
        <div className="bg-ink-900 border border-ink-800 rounded-xl p-4">
          <div className="flex items-center gap-2 font-medium text-ink-200"><Unlock size={17} /> Decoded ZIP</div>
          <p className="text-ink-400 mt-2">Admin recovery/export mode. Protected pages are reconstructed as readable WebPs; legacy pages are copied unchanged.</p>
        </div>
      </div>

      {!selectedSeries ? (
        <div className="text-center py-12 text-ink-500">Select a series to view its chapters.</div>
      ) : chapterLoading ? (
        <div className="flex items-center justify-center gap-2 py-12 text-ink-400"><Loader2 className="animate-spin" size={20} /> Loading chapters…</div>
      ) : (
        <div className="bg-ink-900 border border-ink-800 rounded-xl overflow-hidden">
          {chapters.length === 0 ? (
            <div className="text-center py-10 text-ink-500">No chapters found.</div>
          ) : chapters.map((chapter) => (
            <div key={chapter.id} className="flex flex-col sm:flex-row sm:items-center gap-3 p-4 border-b border-ink-800 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-ink-200">Chapter {chapter.chapter_number}{chapter.title ? ` — ${chapter.title}` : ''}</div>
                <div className="text-xs text-ink-500 mt-1">{chapter.slug} · {chapter.page_count} pages · {chapter.status}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => void download(chapter, 'stored')}
                  disabled={Boolean(downloading)}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 text-sm"
                >
                  {downloading === `${chapter.id}:stored` ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
                  Stored ZIP
                </button>
                <button
                  onClick={() => void download(chapter, 'decoded')}
                  disabled={Boolean(downloading)}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white text-sm"
                >
                  {downloading === `${chapter.id}:decoded` ? <Loader2 className="animate-spin" size={16} /> : <Unlock size={16} />}
                  Decoded ZIP
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
