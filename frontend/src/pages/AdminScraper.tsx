import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ImagePlus,
  Loader2,
  GripVertical,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import {
  api,
  type ScraperBatchItem,
  type ScraperBatchSummary,
  type ScraperChapterDraft,
  type ScraperSeriesDetail,
  type ScraperSeriesSummary,
} from '../api/client';
import SearchableSeriesPicker, {
  type SeriesPickerOption,
} from '../components/SearchableSeriesPicker';
import { usePointerReorder } from '../hooks/usePointerReorder';
import { chapterSlugFromNumber } from '../utils/chapterIdentity';

export default function AdminScraper() {
  const [seriesSearch, setSeriesSearch] = useState('');
  const [seriesList, setSeriesList] = useState<ScraperSeriesSummary[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [selectedSeriesId, setSelectedSeriesId] = useState('');
  const [series, setSeries] = useState<ScraperSeriesDetail | null>(null);

  const [chapterUrl, setChapterUrl] = useState('');
  const [draft, setDraft] = useState<ScraperChapterDraft | null>(null);

  const [chapterNumber, setChapterNumber] = useState('');
  const [chapterSlug, setChapterSlug] = useState('');
  const [chapterTitle, setChapterTitle] = useState('');

  const [newPageUrl, setNewPageUrl] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const seriesRequestRef = useRef(0);
  const batchRequestRef = useRef(0);
  const [published, setPublished] = useState<any>(null);
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [batches, setBatches] = useState<ScraperBatchSummary[]>([]);
  const [failedItems, setFailedItems] = useState<ScraperBatchItem[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);

  const selectedSummary = useMemo(
    () => seriesList.find((item) => item.id === selectedSeriesId) ?? null,
    [seriesList, selectedSeriesId]
  );


  const seriesPickerOptions = useMemo<SeriesPickerOption[]>(
    () =>
      seriesList.map((item) => ({
        id: item.id,
        title: item.title,
        slug: item.slug,
        subtitle: `${item.chapter_count} chapters`,
      })),
    [seriesList]
  );

  const selectedSeriesOption = useMemo<SeriesPickerOption | null>(() => {
    if (selectedSummary) {
      return {
        id: selectedSummary.id,
        title: selectedSummary.title,
        slug: selectedSummary.slug,
        subtitle: `${selectedSummary.chapter_count} chapters`,
      };
    }

    if (series) {
      return {
        id: series.id,
        title: series.title,
        slug: series.slug,
        subtitle: `${series.chapters?.length || 0} chapters`,
      };
    }

    return null;
  }, [selectedSummary, series]);

  const selectSeriesOption = (option: SeriesPickerOption | null) => {
    setSelectedSeriesId(option?.id ?? '');
    setDraft(null);
    setPublished(null);
  };

  const loadSeries = useCallback(async (search: string) => {
    const requestId = ++seriesRequestRef.current;
    setSeriesLoading(true);

    try {
      const rows = await api.scraperSearchSeries(search);
      if (requestId !== seriesRequestRef.current) return;
      setSeriesList(rows);
      setError('');
    } catch (err: any) {
      if (requestId !== seriesRequestRef.current) return;
      setError(err?.detail || err?.message || 'Failed to load series. Showing the last successful matches.');
    } finally {
      if (requestId === seriesRequestRef.current) setSeriesLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSeries(seriesSearch);
    }, 250);

    return () => window.clearTimeout(timer);
  }, [loadSeries, seriesSearch]);

  useEffect(() => {
    if (!selectedSeriesId) {
      setSeries(null);
      return;
    }
    let cancelled = false;
    api.scraperGetSeries(selectedSeriesId)
      .then((value) => { if (!cancelled) setSeries(value); })
      .catch((err: any) => {
        if (!cancelled) setError(err?.detail || 'Failed to load series details.');
      });
    return () => { cancelled = true; };
  }, [selectedSeriesId]);

  useEffect(() => {
    if (draft?.status !== 'publishing') return;

    let cancelled = false;
    const refreshPublication = async () => {
      try {
        const next = await api.scraperGetDraft(draft.id);
        if (cancelled) return;
        setDraft(next);
        if (next.status === 'published' && selectedSeriesId) {
          setSeries(await api.scraperGetSeries(selectedSeriesId));
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.detail || 'Failed to refresh publication status.');
        }
      }
    };

    void refreshPublication();
    const timer = window.setInterval(() => {
      void refreshPublication();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [draft?.id, draft?.status, selectedSeriesId]);

  const createDraft = async () => {
    if (!selectedSeriesId || !chapterUrl.trim()) {
      setError('Select an existing series and enter a chapter URL.');
      return;
    }

    setBusy('scrape');
    setError('');
    setPublished(null);
    setDraft(null);

    try {
      const value = await api.scraperCreateChapterDraft(
        selectedSeriesId,
        chapterUrl.trim()
      );

      setDraft(value);
      setChapterNumber(String(value.chapter_data.chapter_number || ''));
      setChapterSlug(value.chapter_data.chapter_slug || '');
      setChapterTitle(value.chapter_data.chapter_title || '');
    } catch (err: any) {
      setError(err?.detail || 'Scrape failed.');
    } finally {
      setBusy('');
    }
  };

  const retryFailedImages = async () => {
    if (!draft) return;

    setBusy('retry-failed');
    setError('');

    try {
      const value = await api.scraperRetryFailedDraftPages(draft.id);
      setDraft(value);
    } catch (err: any) {
      setError(err?.detail || 'Failed to retry chapter images.');
    } finally {
      setBusy('');
    }
  };

  const refreshDraft = async () => {
    if (!draft) return;
    const value = await api.scraperGetDraft(draft.id);
    setDraft(value);
  };

  const saveChapter = async () => {
    if (!draft) return;

    setBusy('save');
    setError('');

    try {
      const value = await api.scraperUpdateDraftChapter(
        draft.id,
        {
          chapter_number: chapterNumber,
          chapter_slug: chapterSlug,
          chapter_title: chapterTitle.trim() || null,
        }
      );
      setDraft(value);
    } catch (err: any) {
      setError(err?.detail || 'Failed to save chapter metadata.');
    } finally {
      setBusy('');
    }
  };

  const removePage = async (pageId: string) => {
    if (!draft) return;

    setBusy(`remove:${pageId}`);

    try {
      setDraft(await api.scraperRemoveDraftPage(draft.id, pageId));
    } catch (err: any) {
      setError(err?.detail || 'Failed to remove page.');
    } finally {
      setBusy('');
    }
  };

  const movePage = async (pageId: string, delta: number) => {
    if (!draft) return;

    const index = draft.pages.findIndex((page) => page.id === pageId);
    const target = index + delta;

    if (index < 0 || target < 0 || target >= draft.pages.length) return;

    const ids = draft.pages.map((page) => page.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];

    setBusy(`move:${pageId}`);

    try {
      setDraft(await api.scraperReorderDraftPages(draft.id, ids));
    } catch (err: any) {
      setError(err?.detail || 'Failed to reorder pages.');
    } finally {
      setBusy('');
    }
  };

  const previewDraggedPages = useCallback(
    (pages: ScraperChapterDraft['pages']) => {
      setDraft((current) => {
        if (!current) return current;

        return {
          ...current,
          pages: pages.map((page, index) => ({
            ...page,
            order: index + 1,
          })),
        };
      });
    },
    []
  );

  const commitDraggedPages = useCallback(
    async (orderedIds: string[]) => {
      if (!draft) return;

      setBusy('drag-reorder');

      try {
        setDraft(
          await api.scraperReorderDraftPages(
            draft.id,
            orderedIds
          )
        );
      } finally {
        setBusy('');
      }
    },
    [draft?.id]
  );

  const pageReorder = usePointerReorder({
    items: draft?.pages ?? [],
    disabled: Boolean(busy) || draft?.status !== 'draft',
    onPreview: previewDraggedPages,
    onCommit: commitDraggedPages,
    onError: (err: any) => {
      setError(
        err?.detail ||
        err?.message ||
        'Failed to save dragged page order.'
      );
    },
  });

  const replacePageFromUrl = async (pageId: string) => {
    if (!draft) return;

    const requestedUrl = window.prompt('Replacement image URL');
    const replacementUrl = requestedUrl?.trim();
    if (!replacementUrl) return;

    setBusy(`replace:${pageId}`);
    setError('');

    try {
      setDraft(
        await api.scraperReplaceDraftPageUrl(draft.id, pageId, replacementUrl)
      );
    } catch (err: any) {
      setError(err?.detail || 'Failed to replace page.');
    } finally {
      setBusy('');
    }
  };

  const addPageUrl = async () => {
    if (!draft || !newPageUrl.trim()) return;

    setBusy('add-url');
    try {
      setDraft(
        await api.scraperAddDraftPageUrl(
          draft.id,
          newPageUrl.trim()
        )
      );
      setNewPageUrl('');
    } catch (err: any) {
      setError(err?.detail || 'Failed to add page.');
    } finally {
      setBusy('');
    }
  };

  const addPageFile = async (file: File | null) => {
    if (!draft || !file) return;

    setBusy('add-file');
    try {
      setDraft(await api.scraperAddDraftPageFile(draft.id, file));
    } catch (err: any) {
      setError(err?.detail || 'Failed to upload page.');
    } finally {
      setBusy('');
    }
  };

  const publish = async () => {
    if (!draft) return;

    setBusy('publish');
    setError('');

    try {
      // Always persist current metadata immediately before publication.
      const saved = await api.scraperUpdateDraftChapter(
        draft.id,
        {
          chapter_number: chapterNumber,
          chapter_slug: chapterSlug,
          chapter_title: chapterTitle.trim() || null,
        }
      );

      setDraft(saved);

      const result = await api.scraperPublishDraft(draft.id);
      if (result?.status === 'published') {
        setPublished(result);
        if (selectedSeriesId) {
          setSeries(await api.scraperGetSeries(selectedSeriesId));
        }
      } else {
        setPublished(null);
      }

      setDraft(await api.scraperGetDraft(draft.id));
    } catch (err: any) {
      setError(err?.detail || 'Publish failed.');
    } finally {
      setBusy('');
    }
  };


  const refreshBatchQueues = useCallback(async (quiet = false) => {
    const seriesId = selectedSeriesId;
    const requestId = ++batchRequestRef.current;
    if (!seriesId) {
      setBatches([]);
      setFailedItems([]);
      return;
    }

    try {
      const [batchRows, failedRows] = await Promise.all([
        api.scraperListBatches(seriesId),
        api.scraperFailedBatchItems(seriesId),
      ]);
      if (requestId !== batchRequestRef.current) return;
      setBatches(batchRows);
      setFailedItems(failedRows);
      if (!quiet) setError('');
    } catch (err: any) {
      if (requestId !== batchRequestRef.current) return;
      if (!quiet) {
        setError(err?.detail || err?.message || 'Failed to refresh batch queue. Showing the last successful state.');
      }
    }
  }, [selectedSeriesId]);

  useEffect(() => {
    if (!selectedSeriesId) return;
    void refreshBatchQueues(true);
    const active = batches.some((batch) =>
      ['queued', 'processing', 'running'].includes(String(batch.status).toLowerCase())
    );
    const timer = window.setInterval(() => {
      void refreshBatchQueues(true);
    }, active ? 2000 : 8000);
    return () => window.clearInterval(timer);
  }, [selectedSeriesId, batches, refreshBatchQueues]);

  const uploadBatchFolder = async () => {
    if (!selectedSeriesId || batchFiles.length === 0) {
      setError('Select a series and choose a batch folder.');
      return;
    }

    setBatchBusy(true);
    setError('');

    try {
      await api.scraperCreateBatch(selectedSeriesId, batchFiles);
      setBatchFiles([]);
      await refreshBatchQueues();
    } catch (err: any) {
      setError(err?.detail || 'Batch upload failed.');
    } finally {
      setBatchBusy(false);
    }
  };

  const resolveFailed = async (
    item: ScraperBatchItem,
    action: 'discard' | 'overwrite'
  ) => {
    if (
      action === 'overwrite' &&
      !window.confirm(
        `Overwrite existing ${item.chapter_slug}? This deletes the existing chapter and replaces it with the staged batch chapter.`
      )
    ) {
      return;
    }

    setBatchBusy(true);
    setError('');

    try {
      await api.scraperResolveBatchItem(item.id, action);
      await refreshBatchQueues();
    } catch (err: any) {
      setError(err?.detail || 'Failed to resolve batch item.');
    } finally {
      setBatchBusy(false);
    }
  };

  const retryFailed = async (item: ScraperBatchItem) => {
    setBatchBusy(true);

    try {
      await api.scraperRetryBatchItem(item.id);
      await refreshBatchQueues();
    } catch (err: any) {
      setError(err?.detail || 'Failed to retry item.');
    } finally {
      setBatchBusy(false);
    }
  };

  return (
    <div className="w-full min-w-0 max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 sm:gap-4 mb-6">
        <div>
          <Link to="/admin" className="text-ink-400 hover:text-ink-100 text-sm">
            Back to Admin
          </Link>
          <h1 className="font-display text-3xl font-bold mt-2">
            Scraper — Attach Chapter
          </h1>
          <p className="text-ink-400 text-sm mt-1">
            Admin-only. Scrape into a draft, edit pages, then publish into an existing series.
          </p>
        </div>
        <Link
          to="/admin/scraper/new-series"
          className="w-full sm:w-auto px-4 py-3 rounded-xl bg-brand-600 hover:bg-brand-500 text-center text-sm font-medium"
        >
          Scrape New Series
        </Link>
      </div>

      {error && (
        <div className="mb-5 rounded-xl border border-red-700/50 bg-red-900/30 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {published && (
        <div className="mb-5 rounded-xl border border-green-700/50 bg-green-900/30 px-4 py-3 text-sm text-green-300 flex items-center gap-2">
          <CheckCircle2 size={18} />
          Published {published.chapter?.slug} with {published.chapter?.page_count} processed pages.
        </div>
      )}

      <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
        <h2 className="font-display text-xl font-semibold mb-4">1. Choose existing series</h2>

        <SearchableSeriesPicker
          label="Search / select series"
          query={seriesSearch}
          onQueryChange={setSeriesSearch}
          options={seriesPickerOptions}
          selected={selectedSeriesOption}
          onSelect={selectSeriesOption}
          loading={seriesLoading}
          placeholder="Search title or slug…"
          showSelectFallback
          emptyText="No matching series found."
        />

        {series && (
          <div className="mt-5 grid md:grid-cols-[1fr_2fr] gap-5">
            <div className="rounded-xl bg-ink-950 border border-ink-800 p-4">
              <p className="text-xs uppercase text-ink-500 mb-1">Selected series</p>
              <h3 className="mreader-break-anywhere font-semibold text-lg">{series.title}</h3>
              <p className="mreader-break-anywhere text-sm text-ink-400">{series.slug}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                {series.genres?.map((genre) => (
                  <span key={genre.id} className="max-w-full whitespace-normal break-words px-2 py-1 rounded bg-ink-800">
                    {genre.name}
                  </span>
                ))}
              </div>
            </div>

            <div className="rounded-xl bg-ink-950 border border-ink-800 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h3 className="font-semibold">Existing chapters</h3>
                <span className="text-xs text-ink-500">{series.chapters?.length || 0}</span>
              </div>
              <div className="max-h-48 overflow-y-auto space-y-2">
                {series.chapters?.map((chapter) => (
                  <div
                    key={chapter.id}
                    className="flex min-w-0 flex-wrap sm:flex-nowrap justify-between gap-2 sm:gap-3 text-sm border-b border-ink-900 pb-2"
                  >
                    <span className="mreader-break-anywhere min-w-0">
                      Ch. {chapter.chapter_number}
                      {chapter.title ? ` — ${chapter.title}` : ''}
                    </span>
                    <span className="shrink-0 text-ink-500">{chapter.page_count} pages</span>
                  </div>
                ))}
                {!series.chapters?.length && (
                  <p className="text-sm text-ink-500">No chapters yet.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="font-display text-xl font-semibold">2A. Batch upload chapter folders</h2>
            <p className="text-sm text-ink-500 mt-1">
              Choose a parent folder containing chapter folders such as ch-21/, ch-22/, ch-23/.
              Folder names become chapter slugs and chapter numbers automatically.
            </p>
          </div>
          <button
            onClick={() => void refreshBatchQueues(false)}
            disabled={!selectedSeriesId || batchBusy}
            className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm"
          >
            Refresh queues
          </button>
        </div>

        <div className="grid lg:grid-cols-[1fr_auto] gap-3">
          <label className="rounded-xl border border-dashed border-ink-700 bg-ink-950 p-5 cursor-pointer hover:border-brand-600">
            <div className="font-medium">Select chapter batch folder</div>
            <div className="text-sm text-ink-500 mt-1">
              Example: upload-set/ch-21/001.jpg, upload-set/ch-22/001.jpg
            </div>
            <input
              type="file"
              multiple
              className="hidden"
              {...({ webkitdirectory: '', directory: '' } as any)}
              onChange={(e) => {
                setBatchFiles(Array.from(e.target.files || []));
              }}
            />
            {batchFiles.length > 0 && (
              <div className="text-sm text-brand-300 mt-3">
                {batchFiles.length} files selected
              </div>
            )}
          </label>

          <button
            onClick={uploadBatchFolder}
            disabled={!selectedSeriesId || batchFiles.length === 0 || batchBusy}
            className="px-6 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50"
          >
            {batchBusy ? 'Working…' : 'Queue batch'}
          </button>
        </div>

        <div className="mt-6">
          <h3 className="font-semibold mb-3">Batch queue</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-ink-500 border-b border-ink-800">
                <tr>
                  <th className="py-2 pr-3">Batch</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Total</th>
                  <th className="py-2 pr-3">Queued</th>
                  <th className="py-2 pr-3">Processing</th>
                  <th className="py-2 pr-3">Completed</th>
                  <th className="py-2 pr-3">Conflicts</th>
                  <th className="py-2">Errors</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr key={batch.id} className="border-b border-ink-900">
                    <td className="py-2 pr-3 font-mono">{batch.id.slice(0, 8)}</td>
                    <td className="py-2 pr-3">{batch.status}</td>
                    <td className="py-2 pr-3">{batch.total_items}</td>
                    <td className="py-2 pr-3">{batch.queued_items}</td>
                    <td className="py-2 pr-3">{batch.processing_items}</td>
                    <td className="py-2 pr-3 text-green-400">{batch.completed_items}</td>
                    <td className="py-2 pr-3 text-amber-400">{batch.conflict_items}</td>
                    <td className="py-2 text-red-400">{batch.error_items}</td>
                  </tr>
                ))}
                {!batches.length && (
                  <tr>
                    <td colSpan={8} className="py-4 text-ink-500">
                      No batch uploads for this series yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="mt-6">
          <h3 className="font-semibold mb-3">Failed / conflict queue</h3>

          <div className="space-y-3">
            {failedItems.map((item) => (
              <div
                key={item.id}
                className="rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 flex flex-wrap items-center gap-3"
              >
                <div className="w-full sm:w-auto min-w-0 sm:min-w-[170px]">
                  <div className="font-medium">{item.chapter_slug}</div>
                  <div className="text-xs text-ink-500">
                    Chapter {String(item.chapter_number)}
                  </div>
                </div>

                <div className="w-full flex-1 min-w-0 sm:min-w-[220px] text-sm">
                  <span className={item.status === 'failed_conflict' ? 'text-amber-300' : 'text-red-300'}>
                    {item.status}
                  </span>
                  {item.error_message && (
                    <div className="mreader-break-anywhere text-ink-500 mt-1">{item.error_message}</div>
                  )}
                </div>

                {item.status === 'failed_conflict' ? (
                  <>
                    <button
                      onClick={() => resolveFailed(item, 'discard')}
                      disabled={batchBusy}
                      className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700"
                    >
                      Discard staged
                    </button>
                    <button
                      onClick={() => resolveFailed(item, 'overwrite')}
                      disabled={batchBusy}
                      className="px-3 py-2 rounded-lg bg-red-900 text-red-100 hover:bg-red-800"
                    >
                      Overwrite existing
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => retryFailed(item)}
                    disabled={batchBusy}
                    className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700"
                  >
                    Retry
                  </button>
                )}
              </div>
            ))}

            {!failedItems.length && (
              <div className="text-sm text-ink-500">
                No chapters require admin attention.
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
        <h2 className="font-display text-xl font-semibold mb-4">2B. Scrape chapter into editable draft</h2>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={chapterUrl}
            onChange={(e) => setChapterUrl(e.target.value)}
            placeholder="https://source-site.example/series/chapter-123"
            className="flex-1 px-4 py-3 bg-ink-950 border border-ink-800 rounded-xl focus:border-brand-500 focus:outline-none"
          />
          <button
            onClick={createDraft}
            disabled={busy === 'scrape' || !selectedSeriesId}
            className="px-5 py-3 sm:py-0 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {busy === 'scrape' ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
            Scrape
          </button>
        </div>

        {busy === 'scrape' && (
          <div className="mt-4 rounded-xl border border-brand-800/50 bg-brand-950/20 p-4 text-sm text-ink-300 flex items-center gap-3">
            <Loader2 className="animate-spin" size={18} />
            Fetching the chapter page, discovering reader images, and staging valid originals for review…
          </div>
        )}
      </section>

      {draft && (
        <>
          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="font-display text-xl font-semibold">Scrape result</h2>
                <p className="text-sm text-ink-500 mt-1 break-all">
                  {draft.chapter_data.chapter_url}
                </p>
              </div>
              <span className="text-xs px-3 py-1 rounded-full bg-ink-800 text-ink-300">
                {draft.chapter_data.adapter}
              </span>
            </div>

            {draft.chapter_data.scrape_summary ? (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5">
                  <div className="rounded-xl border border-ink-800 bg-ink-950 p-4">
                    <div className="text-2xl font-semibold">
                      {draft.chapter_data.scrape_summary.discovered_count}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">Discovered</div>
                  </div>
                  <div className="rounded-xl border border-green-900/60 bg-green-950/20 p-4">
                    <div className="text-2xl font-semibold text-green-300">
                      {draft.chapter_data.scrape_summary.staged_count}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">Staged successfully</div>
                  </div>
                  <div className="rounded-xl border border-red-900/60 bg-red-950/20 p-4">
                    <div className="text-2xl font-semibold text-red-300">
                      {draft.chapter_data.scrape_summary.failed_count}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">Failed images</div>
                  </div>
                </div>

                {draft.chapter_data.scrape_summary.failed_count > 0 && (
                  <div className="mt-5 rounded-xl border border-amber-900/60 bg-amber-950/20 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                      <div>
                        <h3 className="font-semibold text-amber-200">
                          Some reader images could not be staged
                        </h3>
                        <p className="text-xs text-ink-500 mt-1">
                          Successful images remain in this draft. Retry only the failed CDN requests.
                        </p>
                      </div>
                      <button
                        onClick={retryFailedImages}
                        disabled={busy === 'retry-failed'}
                        className="px-4 py-2 rounded-lg bg-amber-900/50 hover:bg-amber-900 text-amber-100 disabled:opacity-50 flex items-center gap-2 text-sm"
                      >
                        {busy === 'retry-failed' ? (
                          <Loader2 className="animate-spin" size={15} />
                        ) : (
                          <RefreshCw size={15} />
                        )}
                        Retry failed images
                      </button>
                    </div>

                    <div className="max-h-48 overflow-y-auto space-y-2">
                      {draft.chapter_data.scrape_summary.failures.map((failure) => (
                        <div
                          key={`${failure.order}:${failure.source_url}`}
                          className="rounded-lg bg-ink-950/70 border border-ink-800 p-3 text-xs"
                        >
                          <div className="font-medium text-ink-300">
                            Source page {failure.order}
                            {failure.status_code ? ` · HTTP ${failure.status_code}` : ''}
                          </div>
                          <div className="text-red-300 mt-1">{failure.error}</div>
                          <div className="text-ink-600 mt-1 break-all">{failure.source_url}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {draft.pages.length === 0 && (
                  <div className="mt-5 rounded-xl border border-red-800 bg-red-950/30 p-4 text-red-200">
                    The chapter page was parsed, but no images were successfully staged.
                    Use “Retry failed images” or inspect the failed URLs below before publishing.
                  </div>
                )}
              </>
            ) : (
              <div className="mt-4 text-sm text-ink-400">
                {draft.pages.length} images staged.
              </div>
            )}
          </section>

          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
              <h2 className="font-display text-xl font-semibold">3. Edit chapter metadata</h2>
              <span className="text-xs text-ink-500">
                Draft {draft.id.slice(0, 8)}
              </span>
            </div>

            <div className="grid md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-ink-300 mb-1">Chapter number</label>
                <input
                  value={chapterNumber}
                  onChange={(e) => {
                    const value = e.target.value;
                    setChapterNumber(value);
                    setChapterSlug(chapterSlugFromNumber(value));
                  }}
                  className="w-full px-4 py-3 bg-ink-950 border border-ink-800 rounded-xl"
                />
              </div>
              <div>
                <label className="block text-sm text-ink-300 mb-1">Chapter slug</label>
                <input
                  value={chapterSlug}
                  readOnly
                  tabIndex={-1}
                  title="Automatically generated from the chapter number"
                  className="w-full px-4 py-3 bg-ink-950/70 border border-ink-800 rounded-xl text-ink-400 cursor-default"
                />
                <p className="text-xs text-ink-500 mt-1">Generated automatically from the chapter number.</p>
              </div>
              <div>
                <label className="block text-sm text-ink-300 mb-1">Chapter title</label>
                <input
                  value={chapterTitle}
                  onChange={(e) => setChapterTitle(e.target.value)}
                  className="w-full px-4 py-3 bg-ink-950 border border-ink-800 rounded-xl"
                />
                <p className="text-xs text-ink-500 mt-1">Optional display title. It does not affect the chapter slug.</p>
              </div>
            </div>

            <button
              onClick={saveChapter}
              disabled={busy === 'save'}
              className="mt-4 px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700"
            >
              Save Draft Metadata
            </button>
          </section>

          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  4. Review / reorder / remove pages
                </h2>
                <p className="text-sm text-ink-500">
                  {draft.pages.length} staged originals. WebP processing happens only when you publish.
                </p>
              </div>

              <button
                onClick={refreshDraft}
                className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 flex items-center gap-2 text-sm"
              >
                <RefreshCw size={15} />
                Refresh
              </button>
            </div>

            <div className="mb-4 rounded-xl border border-brand-900/40 bg-brand-950/20 px-4 py-3 text-sm text-ink-300 flex items-start gap-3">
              <GripVertical size={18} className="text-brand-400 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium text-ink-200">Drag to reorder</div>
                <div className="text-xs text-ink-500 mt-0.5">
                  Hold the left or right mouse button on a page card and drag across the cards.
                  The order previews immediately and is saved once you release the button.
                </div>
              </div>
            </div>

            <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {draft.pages.map((page, index) => (
                <div
                  key={page.id}
                  data-page-id={page.id}
                  onPointerDown={(event) =>
                    pageReorder.startReorder(event, page.id)
                  }
                  onPointerEnter={(event) =>
                    pageReorder.enterReorderTarget(event, page.id)
                  }
                  onPointerUp={pageReorder.finishReorder}
                  onContextMenu={(event) => event.preventDefault()}
                  className={`rounded-xl overflow-hidden border bg-ink-950 transition-all select-none cursor-grab active:cursor-grabbing ${
                    pageReorder.draggedId === page.id
                      ? 'border-brand-400 ring-2 ring-brand-500/40 scale-[1.02] opacity-80'
                      : 'border-ink-800 hover:border-ink-600'
                  }`}
                >
                  <div className="aspect-[3/4] bg-black flex items-center justify-center">
                    <img
                      src={`/api/scraper/drafts/${draft.id}/pages/${page.id}/preview`}
                      alt={`Page ${index + 1}`}
                      className="max-h-full max-w-full object-contain"
                      onError={(event) => {
                        event.currentTarget.style.opacity = '0.25';
                        event.currentTarget.alt = `Page ${index + 1} preview failed`;
                      }}
                    />
                  </div>

                  <div className="p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium">Page {index + 1}</span>
                      <span className="text-xs text-ink-600">
                        {page.content_type}
                      </span>
                    </div>

                    <div className="flex gap-2 items-center">
                      <span
                        className="p-2 rounded bg-brand-950/40 text-brand-400"
                        title="Hold left or right mouse button and drag"
                      >
                        <GripVertical size={15} />
                      </span>
                      <button
                        onClick={() => movePage(page.id, -1)}
                        disabled={index === 0 || busy.startsWith('move:')}
                        className="p-2 rounded bg-ink-800 disabled:opacity-30"
                        title="Move up"
                      >
                        <ArrowUp size={15} />
                      </button>
                      <button
                        onClick={() => movePage(page.id, 1)}
                        disabled={index === draft.pages.length - 1 || busy.startsWith('move:')}
                        className="p-2 rounded bg-ink-800 disabled:opacity-30"
                        title="Move down"
                      >
                        <ArrowDown size={15} />
                      </button>
                      <button
                        onClick={() => void replacePageFromUrl(page.id)}
                        disabled={busy === `replace:${page.id}`}
                        className="p-2 rounded bg-ink-800 disabled:opacity-30"
                        title="Replace from URL"
                      >
                        <ImagePlus size={15} />
                        <span className="sr-only">Replace from URL</span>
                      </button>
                      <button
                        onClick={() => removePage(page.id)}
                        disabled={busy === `remove:${page.id}`}
                        className="ml-auto p-2 rounded bg-red-950 text-red-300 hover:bg-red-900"
                        title="Remove page"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="grid md:grid-cols-2 gap-4 mt-6">
              <div className="rounded-xl border border-ink-800 p-4">
                <h3 className="font-semibold mb-3">Add image URL</h3>
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    value={newPageUrl}
                    onChange={(e) => setNewPageUrl(e.target.value)}
                    placeholder="https://.../page.jpg"
                    className="flex-1 min-w-0 px-3 py-2 bg-ink-950 border border-ink-800 rounded-lg"
                  />
                  <button
                    onClick={addPageUrl}
                    disabled={busy === 'add-url'}
                    className="px-3 py-2 sm:py-0 rounded-lg bg-ink-800 hover:bg-ink-700"
                  >
                    Add
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-ink-800 p-4">
                <h3 className="font-semibold mb-3">Upload missing/replacement page</h3>
                <label className="flex items-center justify-center gap-2 py-3 rounded-lg bg-ink-800 hover:bg-ink-700 cursor-pointer">
                  <ImagePlus size={17} />
                  Add local image
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => addPageFile(e.target.files?.[0] || null)}
                  />
                </label>
              </div>
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-brand-800/50 bg-brand-950/20 p-4 sm:p-5">
            <h2 className="font-display text-xl font-semibold mb-2">5. Publish into {selectedSeriesOption?.title}</h2>
            <p className="text-sm text-ink-400 mb-4">
              Selected staged images stay in the Scraper staging area until Media accepts the job.
              Media performs the final v4 conversion and immutable upload, then Catalog commits the
              chapter/pages and publication receipt atomically.
            </p>

            <button
              onClick={publish}
              disabled={busy === 'publish' || draft.status !== 'draft' || draft.pages.length === 0}
              className="px-6 py-3 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 flex items-center gap-2"
            >
              {busy === 'publish' && <Loader2 className="animate-spin" size={18} />}
              Publish Chapter
            </button>

            {draft.status === 'publishing' && (
              <p className="mt-3 text-sm text-amber-300">
                Publication is still being reconciled by Media and Catalog. This page will refresh the
                durable state automatically; refreshing the browser is also safe.
              </p>
            )}

            {draft.status === 'published' && (
              <p className="mt-3 text-sm text-green-400">
                This draft has been published with a durable Catalog receipt.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
