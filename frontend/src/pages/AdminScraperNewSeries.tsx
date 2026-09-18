import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  GripVertical,
  ImagePlus,
  AlertTriangle,
  BookOpen,
  ExternalLink,
  Loader2,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import {
  api,
  type ScraperSeriesDraft,
  type ScraperSeriesDraftChapter,
  type ScraperOperationEvent,
} from '../api/client';
import { usePointerReorder } from '../hooks/usePointerReorder';
import { kebabCase } from '../utils/slug';
import { chapterSlugFromNumber } from '../utils/chapterIdentity';

const splitCsv = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

const ACTIVE_DRAFT_STORAGE_KEY =
  'mreader.scraper.newSeries.activeDraftId';
const EXPANDED_CHAPTER_STORAGE_KEY =
  'mreader.scraper.newSeries.expandedChapterId';

const readStoredValue = (key: string): string => {
  try {
    return window.localStorage.getItem(key) || '';
  } catch {
    return '';
  }
};

const writeStoredValue = (key: string, value: string) => {
  try {
    if (value) {
      window.localStorage.setItem(key, value);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Browser storage can be unavailable in restrictive/private contexts.
  }
};

const getDraftIdFromLocation = (): string => {
  try {
    return new URL(window.location.href).searchParams.get('draft') || '';
  } catch {
    return '';
  }
};

const replaceDraftInLocation = (draftId: string) => {
  try {
    const url = new URL(window.location.href);

    if (draftId) {
      url.searchParams.set('draft', draftId);
    } else {
      url.searchParams.delete('draft');
    }

    window.history.replaceState(
      window.history.state,
      '',
      `${url.pathname}${url.search}${url.hash}`
    );
  } catch {
    // URL persistence is best-effort; localStorage remains the fallback.
  }
};

export default function AdminScraperNewSeries() {
  const [sourceUrl, setSourceUrl] = useState('');
  const [recursiveDiscovery, setRecursiveDiscovery] = useState(true);
  const [crawlDepth, setCrawlDepth] = useState(1);
  const [crawlMaxPages, setCrawlMaxPages] = useState(20);
  const [draft, setDraft] = useState<ScraperSeriesDraft | null>(null);
  const draftRef = useRef<ScraperSeriesDraft | null>(null);
  const [title, setTitle] = useState('');
  const [slug, setSlug] = useState('');
  const [seriesSlugTouched, setSeriesSlugTouched] = useState(false);
  const [description, setDescription] = useState('');
  const [seriesStatus, setSeriesStatus] = useState('ongoing');
  const [genres, setGenres] = useState('');
  const [tags, setTags] = useState('');
  const [coverUrl, setCoverUrl] = useState('');
  const [expandedChapterId, setExpandedChapterId] = useState('');
  const [newPageUrl, setNewPageUrl] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [flowEvents, setFlowEvents] = useState<ScraperOperationEvent[]>([]);
  const [flowTotal, setFlowTotal] = useState(0);
  const [flowNextBeforeId, setFlowNextBeforeId] = useState<string | null>(null);
  const [flowLoadingOlder, setFlowLoadingOlder] = useState(false);
  const [flowError, setFlowError] = useState('');

  const [resumeState, setResumeState] = useState<
    'idle' | 'loading' | 'resumed'
  >('idle');

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const selected = useMemo(
    () => draft?.chapters.filter((chapter) => chapter.selected) ?? [],
    [draft]
  );


  const editableWorkflow = Boolean(
    draft &&
      !draft.published_series_id &&
      ['draft', 'ready', 'failed'].includes(draft.workflow_status)
  );

  const stageableWorkflow = Boolean(
    draft &&
      ['draft', 'ready', 'failed', 'published_partial', 'cancelled'].includes(
        draft.workflow_status
      )
  );

  const workflowBusy = Boolean(
    draft &&
      ['queued_discovery', 'discovering', 'staging', 'queued_publish', 'publishing'].includes(
        draft.workflow_status
      )
  );

  const selectedReadyCount = useMemo(
    () =>
      selected.filter((chapter) =>
        ['ready', 'published'].includes(chapter.stage_status)
      ).length,
    [selected]
  );

  const selectedFailedCount = useMemo(
    () =>
      selected.filter((chapter) => chapter.stage_status === 'error').length,
    [selected]
  );

  const selectedPendingCount = useMemo(
    () =>
      selected.filter((chapter) =>
        ['queued', 'staging'].includes(chapter.stage_status)
      ).length,
    [selected]
  );

  const selectedNeedStageCount = useMemo(
    () =>
      selected.filter(
        (chapter) =>
          !['ready', 'published'].includes(chapter.stage_status)
      ).length,
    [selected]
  );

  const allSelectedReady =
    selected.length > 0 &&
    selected.every((chapter) =>
      ['ready', 'published'].includes(chapter.stage_status)
    );

  const selectedPublishableCount = useMemo(
    () =>
      selected.filter(
        (chapter) =>
          chapter.stage_status === 'ready' &&
          chapter.publish_status !== 'published' &&
          !chapter.published_chapter_id
      ).length,
    [selected]
  );

  const chapterPublishCounts = useMemo(
    () =>
      selected.reduce(
        (counts, chapter) => {
          const status = chapter.published_chapter_id
            ? 'published'
            : chapter.publish_status || 'pending';

          if (status === 'published') counts.published += 1;
          else if (status === 'failed') counts.failed += 1;
          else if (status === 'skipped') counts.skipped += 1;
          else if (status === 'cancelled') counts.cancelled += 1;
          else if (status === 'publishing') counts.publishing += 1;
          else counts.pending += 1;

          return counts;
        },
        {
          published: 0,
          failed: 0,
          skipped: 0,
          cancelled: 0,
          publishing: 0,
          pending: 0,
        }
      ),
    [selected]
  );
  const terminalChapterCount =
    chapterPublishCounts.published +
    chapterPublishCounts.failed +
    chapterPublishCounts.skipped +
    chapterPublishCounts.cancelled;

  const canPublish =
    Boolean(draft) &&
    ['ready', 'failed', 'staging', 'published_partial', 'cancelled'].includes(
      draft!.workflow_status
    ) &&
    (selectedPublishableCount > 0 || selectedPendingCount > 0);

  const discoveryProgress = draft?.discovery_progress;
  const discoveryPercent = Math.max(
    0,
    Math.min(100, Number(discoveryProgress?.percent ?? 0))
  );
  const discoveryInFlight = Boolean(
    draft && ['queued_discovery', 'discovering'].includes(draft.workflow_status)
  );

  const chapterTitlesSuppressed = Boolean(
    draft?.chapter_titles_suppressed ||
      draft?.discovery_options?.suppress_chapter_titles
  );
  const chapterTitleClearAllowed = Boolean(
    draft &&
      !draft.operation_cancel_requested_at &&
      !['queued_publish', 'publishing', 'published', 'duplicate'].includes(
        draft.workflow_status
      ) &&
      !draft.chapters.some((chapter) => chapter.publish_status === 'publishing')
  );

  const publishProgress = draft?.publish_progress;
  const publishPercent = Math.max(
    0,
    Math.min(100, Number(publishProgress?.percent ?? 0))
  );
  const publishInFlight = Boolean(
    draft &&
      ['queued_publish', 'publishing'].includes(draft.workflow_status)
  );
  const singleChapterPublishInFlight = Boolean(
    draft?.chapters.some(
      (chapter) =>
        !chapter.published_chapter_id &&
        ['pending', 'publishing'].includes(chapter.publish_status) &&
        chapter.publish_progress?.mode === 'single'
    )
  );
  const chapterEditingLocked = Boolean(
    draft &&
      (workflowBusy ||
        singleChapterPublishInFlight ||
        Boolean(draft.operation_cancel_requested_at))
  );

  const isChapterMutationLocked = useCallback(
    (chapter: ScraperSeriesDraftChapter) =>
      chapterEditingLocked ||
      Boolean(chapter.published_chapter_id) ||
      chapter.stage_status === 'published' ||
      chapter.publish_status === 'published' ||
      ['queued', 'staging'].includes(chapter.stage_status) ||
      chapter.publish_status === 'publishing' ||
      (chapter.publish_progress?.mode === 'single' &&
        ['pending', 'publishing'].includes(chapter.publish_status)),
    [chapterEditingLocked]
  );

  const publishFinished =
    draft?.workflow_status === 'published' ||
    draft?.workflow_status === 'published_partial';
  const publishPartial =
    draft?.workflow_status === 'published_partial';
  const publishCancelled =
    draft?.workflow_status === 'cancelled';
  const publishFailed =
    draft?.workflow_status === 'failed' &&
    Boolean(publishPercent > 0);
  const verificationWarning =
    publishFinished &&
    [
      'completed_with_warnings',
      'completed_with_chapter_failures',
    ].includes(publishProgress?.phase || '');

  const expanded = useMemo(
    () => draft?.chapters.find((chapter) => chapter.id === expandedChapterId) ?? null,
    [draft, expandedChapterId]
  );

  const loadDraft = (
    value: ScraperSeriesDraft,
    options: { persist?: boolean; restoreExpanded?: boolean } = {}
  ) => {
    const {
      persist = true,
      restoreExpanded = false,
    } = options;

    draftRef.current = value;
    setDraft(value);
    setSourceUrl(value.source_url || '');
    setTitle(value.title);
    setSlug(value.slug);
    setSeriesSlugTouched(false);
    setDescription(value.description || '');
    setSeriesStatus(value.series_status);
    setGenres(value.genres.join(', '));
    setTags(value.tags.join(', '));
    setCoverUrl(value.cover_source_url || '');

    if (persist) {
      writeStoredValue(ACTIVE_DRAFT_STORAGE_KEY, value.id);
      replaceDraftInLocation(value.id);
    }

    if (restoreExpanded) {
      const rememberedChapterId = readStoredValue(
        EXPANDED_CHAPTER_STORAGE_KEY
      );

      if (
        rememberedChapterId &&
        value.chapters.some(
          (chapter) => chapter.id === rememberedChapterId
        )
      ) {
        setExpandedChapterId(rememberedChapterId);
      } else {
        setExpandedChapterId('');
        writeStoredValue(EXPANDED_CHAPTER_STORAGE_KEY, '');
      }
    } else if (
      expandedChapterId &&
      !value.chapters.some(
        (chapter) => chapter.id === expandedChapterId
      )
    ) {
      setExpandedChapterId('');
      writeStoredValue(EXPANDED_CHAPTER_STORAGE_KEY, '');
    }
  };

  const clearActiveDraftPersistence = () => {
    writeStoredValue(ACTIVE_DRAFT_STORAGE_KEY, '');
    writeStoredValue(EXPANDED_CHAPTER_STORAGE_KEY, '');
    replaceDraftInLocation('');
  };

  const startNewScrape = () => {
    clearActiveDraftPersistence();

    setDraft(null);
    setSourceUrl('');
    setTitle('');
    setSlug('');
    setSeriesSlugTouched(false);
    setDescription('');
    setSeriesStatus('ongoing');
    setGenres('');
    setTags('');
    setCoverUrl('');
    setExpandedChapterId('');
    setNewPageUrl('');
    setBusy('');
    setError('');
    setResumeState('idle');
  };

  useEffect(() => {
    const draftId =
      getDraftIdFromLocation() ||
      readStoredValue(ACTIVE_DRAFT_STORAGE_KEY);

    if (!draftId) {
      return;
    }

    let cancelled = false;
    setResumeState('loading');
    setBusy('resume');

    void (async () => {
      try {
        const value = await api.scraperGetSeriesDraft(draftId);

        if (cancelled) return;

        loadDraft(value, {
          persist: true,
          restoreExpanded: true,
        });
        setResumeState('resumed');
      } catch (err: any) {
        if (cancelled) return;

        clearActiveDraftPersistence();
        setResumeState('idle');
        setError(
          err?.detail ||
            err?.message ||
            'The previously active scraper draft could not be restored.'
        );
      } finally {
        if (!cancelled) {
          setBusy('');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (
      !draft ||
      !['queued_discovery', 'discovering', 'staging', 'queued_publish', 'publishing'].includes(
        draft.workflow_status
      ) &&
      selectedPendingCount === 0 &&
      !singleChapterPublishInFlight
    ) {
      return;
    }

    let cancelled = false;
    let pollInFlight = false;

    const poll = async () => {
      if (pollInFlight) return;
      pollInFlight = true;
      try {
        const latest = await api.scraperGetSeriesPublishStatus(draft.id);
        try {
          const flow = await api.scraperGetSeriesOperationEvents(draft.id, 250);
          if (!cancelled) {
            setFlowEvents((current) => {
              const byId = new Map<string, ScraperOperationEvent>();
              [...flow.items, ...current].forEach((item) => byId.set(item.id, item));
              return [...byId.values()].sort(
                (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
              );
            });
            setFlowTotal(flow.total);
            setFlowNextBeforeId((current) => current ?? flow.next_before_id);
            setFlowError('');
          }
        } catch (flowErr: any) {
          if (!cancelled) {
            setFlowError(
              flowErr?.detail ||
                flowErr?.message ||
                'Operation data-flow timeline is unavailable.'
            );
          }
        }

        // The workflow endpoint stays lightweight and returns page_count only.
        // Hydrate only chapters whose backend page count changed.  Limit each
        // poll to four one-shot hydrations so a large series cannot cause a
        // burst of hundreds of page-payload requests when workers finish at
        // the same time. Failed hydration is retried by the next status poll.
        const snapshot = draftRef.current;
        const snapshotById = new Map(
          (snapshot?.chapters ?? []).map((chapter) => [chapter.id, chapter])
        );
        const hydrationTargets = latest.chapters
          .filter((status) => {
            const local = snapshotById.get(status.id);
            return (
              status.stage_status === 'ready' &&
              Number(status.page_count || 0) !== Number(local?.pages.length || 0)
            );
          })
          .slice(0, 4);

        const hydratedPagesById = new Map<string, ScraperSeriesDraftChapter['pages']>();
        if (hydrationTargets.length) {
          const results = await Promise.allSettled(
            hydrationTargets.map((status) =>
              api.scraperGetSeriesDraftChapterPages(draft.id, status.id)
            )
          );
          results.forEach((result, index) => {
            if (result.status === 'fulfilled') {
              hydratedPagesById.set(hydrationTargets[index].id, result.value.pages);
            }
          });
        }

        const previousSnapshot = draftRef.current;
        const discoveryJustFinished = Boolean(
          previousSnapshot &&
            ['queued_discovery', 'discovering'].includes(previousSnapshot.workflow_status) &&
            !['queued_discovery', 'discovering'].includes(latest.workflow_status)
        );

        if (discoveryJustFinished) {
          const fullDraft = await api.scraperGetSeriesDraft(draft.id);
          if (!cancelled) {
            loadDraft(fullDraft, { persist: false });
          }
          return;
        }

        if (!cancelled) {
          setDraft((current) => {
            if (!current || current.id !== latest.id) return current;
            const byId = new Map(latest.chapters.map((chapter) => [chapter.id, chapter]));
            const next = {
              ...current,
              workflow_status: latest.workflow_status,
              error_message: latest.error_message,
              published_series_id: latest.published_series_id,
              publish_attempt: latest.publish_attempt,
              publish_started_at: latest.publish_started_at,
              publish_finished_at: latest.publish_finished_at,
              publish_cancel_requested_at: latest.publish_cancel_requested_at,
              publish_worker_heartbeat_at: latest.publish_worker_heartbeat_at,
              publish_progress: latest.publish_progress,
              discovery_progress: latest.discovery_progress ?? current.discovery_progress,
              chapters: current.chapters.map((chapter) => {
                const status = byId.get(chapter.id);
                if (!status) return chapter;
                return {
                  ...chapter,
                  ...status,
                  pages: hydratedPagesById.get(chapter.id) ?? chapter.pages,
                };
              }),
            };
            draftRef.current = next;
            return next;
          });
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(
            err?.detail ||
              err?.message ||
              'Failed to refresh scraper workflow status.'
          );
        }
      } finally {
        pollInFlight = false;
      }
    };

    const timer = window.setInterval(() => {
      void poll();
    }, 2000);

    void poll();

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [draft?.id, draft?.workflow_status, selectedPendingCount, singleChapterPublishInFlight]);

  useEffect(() => {
    if (!draft?.id) {
      setFlowEvents([]);
      setFlowTotal(0);
      setFlowNextBeforeId(null);
      setFlowError('');
      return;
    }
    let cancelled = false;
    void api.scraperGetSeriesOperationEvents(draft.id, 250)
      .then((flow) => {
        if (!cancelled) {
          setFlowEvents(flow.items);
          setFlowTotal(flow.total);
          setFlowNextBeforeId(flow.next_before_id);
          setFlowError('');
        }
      })
      .catch((flowErr: any) => {
        if (!cancelled) {
          setFlowError(
            flowErr?.detail ||
              flowErr?.message ||
              'Operation data-flow timeline is unavailable.'
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [draft?.id]);

  const loadOlderFlowEvents = async () => {
    if (!draft?.id || !flowNextBeforeId || flowLoadingOlder) return;
    setFlowLoadingOlder(true);
    try {
      const flow = await api.scraperGetSeriesOperationEvents(draft.id, 250, flowNextBeforeId);
      setFlowEvents((current) => {
        const byId = new Map(current.map((item) => [item.id, item] as const));
        flow.items.forEach((item) => byId.set(item.id, item));
        return [...byId.values()].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
      });
      setFlowTotal(flow.total);
      setFlowNextBeforeId(flow.next_before_id);
      setFlowError('');
    } catch (flowErr: any) {
      setFlowError(flowErr?.detail || flowErr?.message || 'Could not load older data-flow events.');
    } finally {
      setFlowLoadingOlder(false);
    }
  };

  const discover = async () => {
    if (!sourceUrl.trim()) return;

    setBusy('discover');
    setError('');

    try {
      loadDraft(
        await api.scraperDiscoverSeriesDraft(sourceUrl.trim(), {
          recursive: recursiveDiscovery,
          maxDepth: crawlDepth,
          maxPages: crawlMaxPages,
        })
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Series discovery failed. Check the source URL and scraper diagnostics.'
      );
    } finally {
      setBusy('');
    }
  };

  const refresh = async () => {
    if (!draft) return;
    loadDraft(await api.scraperGetSeriesDraft(draft.id));
  };

  const persistMetadata = async (
    draftId: string
  ): Promise<ScraperSeriesDraft> => {
    return api.scraperUpdateSeriesDraft(draftId, {
      title,
      slug,
      description: description.trim() || null,
      series_status: seriesStatus,
      genres: splitCsv(genres),
      tags: splitCsv(tags),
    });
  };

  const saveMetadata = async () => {
    if (!draft || !editableWorkflow) return;

    setBusy('metadata');
    setError('');

    try {
      loadDraft(await persistMetadata(draft.id));
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Failed to save metadata.'
      );
    } finally {
      setBusy('');
    }
  };

  const previewChapterPatch = useCallback((
    chapterId: string,
    patch: Partial<ScraperSeriesDraftChapter>
  ) => {
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        chapters: current.chapters.map((chapter) =>
          chapter.id === chapterId ? { ...chapter, ...patch } : chapter
        ),
      };
    });
  }, []);

  const updateChapter = async (
    chapter: ScraperSeriesDraftChapter,
    patch: Partial<{
      chapter_number: string;
      chapter_slug: string;
      chapter_title: string | null;
      selected: boolean;
    }>
  ) => {
    if (!draft) return;

    try {
      loadDraft(
        await api.scraperUpdateSeriesDraftChapter(chapter.id, {
          chapter_number: String(patch.chapter_number ?? chapter.chapter_number),
          chapter_slug: patch.chapter_slug ?? chapter.chapter_slug,
          chapter_title:
            patch.chapter_title === undefined
              ? chapter.chapter_title
              : patch.chapter_title,
          selected: patch.selected ?? chapter.selected,
        })
      );
    } catch (err: any) {
      setError(err?.detail || 'Failed to update chapter.');
    }
  };

  const clearAllChapterTitles = async () => {
    if (!draft || !chapterTitleClearAllowed) return;

    const titledCount = draft.chapters.filter(
      (chapter) => Boolean(chapter.chapter_title?.trim())
    ).length;

    const confirmed = window.confirm(
      discoveryInFlight
        ? 'Clear chapter titles for this scrape? Existing titles will be removed and chapters discovered by the running update will also remain untitled. Chapter numbers and generated slugs will not change.'
        : `Clear the titles from ${titledCount || 'all'} chapter${titledCount === 1 ? '' : 's'}? Chapter numbers and generated slugs will not change.`
    );

    if (!confirmed) return;

    setBusy('clear-chapter-titles');
    setError('');

    try {
      loadDraft(
        await api.scraperClearSeriesDraftChapterTitles(draft.id)
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Failed to clear chapter titles.'
      );
    } finally {
      setBusy('');
    }
  };

  const stageSelected = async () => {
    if (!draft || !stageableWorkflow) return;

    const ids = selected
      .filter(
        (chapter) =>
          !['ready', 'published'].includes(chapter.stage_status)
      )
      .map((chapter) => chapter.id);

    if (!ids.length) return;

    setBusy('stage');
    setError('');

    try {
      // Metadata is editable only before production publication has begun. A
      // partial/cancelled operation can still retry staging without silently
      // failing on the stricter metadata state machine.
      if (editableWorkflow) {
        const saved = await persistMetadata(draft.id);
        loadDraft(saved);
      }

      loadDraft(
        await api.scraperStageSeriesChapters(
          draft.id,
          ids
        )
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Failed to queue chapter staging.'
      );
    } finally {
      setBusy('');
    }
  };

  const replaceCover = async () => {
    if (!draft || !coverUrl.trim()) return;

    setBusy('cover');
    try {
      loadDraft(
        await api.scraperReplaceSeriesCoverUrl(draft.id, coverUrl.trim())
      );
    } catch (err: any) {
      setError(err?.detail || 'Failed to replace cover.');
    } finally {
      setBusy('');
    }
  };

  const removePage = async (chapterId: string, pageId: string) => {
    setBusy(`page:${pageId}`);
    try {
      loadDraft(await api.scraperRemoveSeriesDraftPage(chapterId, pageId));
    } catch (err: any) {
      setError(err?.detail || 'Failed to remove page.');
    } finally {
      setBusy('');
    }
  };

  const movePage = async (
    chapter: ScraperSeriesDraftChapter,
    pageId: string,
    delta: number
  ) => {
    const index = chapter.pages.findIndex((page) => page.id === pageId);
    const target = index + delta;

    if (target < 0 || target >= chapter.pages.length) return;

    const ids = chapter.pages.map((page) => page.id);
    [ids[index], ids[target]] = [ids[target], ids[index]];

    setBusy(`move:${pageId}`);
    try {
      loadDraft(await api.scraperReorderSeriesDraftPages(chapter.id, ids));
    } catch (err: any) {
      setError(err?.detail || 'Failed to reorder pages.');
    } finally {
      setBusy('');
    }
  };

  const previewExpandedPages = useCallback(
    (pages: ScraperSeriesDraftChapter['pages']) => {
      if (!expandedChapterId) return;

      setDraft((current) => {
        if (!current) return current;

        return {
          ...current,
          chapters: current.chapters.map((chapter) =>
            chapter.id === expandedChapterId
              ? {
                  ...chapter,
                  pages: pages.map((page, index) => ({
                    ...page,
                    order: index + 1,
                  })),
                }
              : chapter
          ),
        };
      });
    },
    [expandedChapterId]
  );

  const commitExpandedPageOrder = useCallback(
    async (orderedIds: string[]) => {
      if (!expanded) return;

      setBusy('drag-reorder');

      try {
        loadDraft(
          await api.scraperReorderSeriesDraftPages(
            expanded.id,
            orderedIds
          )
        );
      } finally {
        setBusy('');
      }
    },
    [expanded?.id]
  );

  const expandedPageReorder = usePointerReorder({
    items: expanded?.pages ?? [],
    disabled:
      Boolean(busy) ||
      !expanded ||
      expanded.stage_status === 'published',
    onPreview: previewExpandedPages,
    onCommit: commitExpandedPageOrder,
    onError: (err: any) => {
      setError(
        err?.detail ||
        err?.message ||
        'Failed to save dragged page order.'
      );
    },
  });

  const addPageUrl = async () => {
    if (!expanded || !newPageUrl.trim()) return;

    setBusy('add-page-url');
    try {
      loadDraft(
        await api.scraperAddSeriesDraftPageUrl(
          expanded.id,
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

  const stageOneChapter = async (chapter: ScraperSeriesDraftChapter) => {
    if (!draft) return;

    setBusy(`stage-chapter:${chapter.id}`);
    setError('');
    try {
      loadDraft(
        await api.scraperStageSeriesChapters(draft.id, [chapter.id])
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          `Failed to stage ${chapter.chapter_slug}.`
      );
    } finally {
      setBusy('');
    }
  };

  const publishOneChapter = async (chapter: ScraperSeriesDraftChapter) => {
    if (!draft) return;

    setBusy(`publish-chapter:${chapter.id}`);
    setError('');
    try {
      // Save edited series metadata before the first independent publish so
      // the production series is created from what the admin is reviewing.
      let latest = await api.scraperGetSeriesDraft(draft.id);
      if (
        !latest.published_series_id &&
        ['draft', 'ready', 'failed'].includes(latest.workflow_status)
      ) {
        latest = await persistMetadata(latest.id);
        loadDraft(latest);
      }
      setDraft((current) => current ? {
        ...current,
        chapters: current.chapters.map((item) =>
          item.id === chapter.id
            ? {
                ...item,
                publish_status: 'pending',
                publish_error: null,
                publish_progress: {
                  ...item.publish_progress,
                  mode: 'single',
                  phase: 'queued_single',
                  percent: 0,
                  message: 'Publish request accepted. Waiting for the scraper worker.',
                },
              }
            : item
        ),
      } : current);
      await api.scraperPublishSeriesDraftChapter(latest.id, chapter.id);
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          `Failed to queue ${chapter.chapter_slug} for publish.`
      );
    } finally {
      setBusy('');
    }
  };

  const publish = async () => {
    if (!draft) return;

    setBusy('publish');
    setError('');

    try {
      const latest = await api.scraperGetSeriesDraft(draft.id);
      loadDraft(latest);

      const latestSelected = latest.chapters.filter(
        (chapter) => chapter.selected
      );
      const publishable = latestSelected.filter(
        (chapter) =>
          chapter.stage_status === 'ready' &&
          chapter.publish_status !== 'published' &&
          !chapter.published_chapter_id
      );

      if (
        ['queued_publish', 'publishing'].includes(
          latest.workflow_status
        )
      ) {
        return;
      }

      const stagingSelected = latestSelected.filter((chapter) =>
        ['queued', 'staging'].includes(chapter.stage_status)
      );
      if (!publishable.length && !stagingSelected.length) {
        throw new Error(
          'No selected chapters are ready or still staging for this publish operation.'
        );
      }

      if (
        !latest.published_series_id &&
        ['ready', 'failed'].includes(latest.workflow_status)
      ) {
        const saved = await persistMetadata(latest.id);
        loadDraft(saved);
      }

      loadDraft(
        await api.scraperPublishSeriesDraft(latest.id)
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Failed to queue publish.'
      );
    } finally {
      setBusy('');
    }
  };

  const cancelPublish = async () => {
    if (!draft || !publishInFlight) return;

    const confirmed = window.confirm(
      'Cancel this publish job? Chapters already committed will remain live. ' +
      'The current uncommitted chapter and remaining chapters will stop.'
    );
    if (!confirmed) return;

    setBusy('cancel-publish');
    setError('');

    try {
      loadDraft(
        await api.scraperCancelSeriesPublish(draft.id)
      );
    } catch (err: any) {
      setError(
        err?.detail ||
          err?.message ||
          'Failed to request publish cancellation.'
      );
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="w-full min-w-0 max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Link
              to="/admin/scraper"
              className="text-ink-400 hover:text-ink-100 text-sm"
            >
              Back to Scraper
            </Link>
            <Link
              to="/admin/scraper/operations"
              className="text-brand-400 hover:text-brand-300 text-sm"
            >
              Scrape operations
            </Link>
          </div>

          {draft && (
            <button
              type="button"
              onClick={startNewScrape}
              className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm"
            >
              Start new scrape
            </button>
          )}
        </div>

        <h1 className="mreader-break-anywhere font-display text-2xl sm:text-3xl font-bold mt-2">
          Scrape New Series
        </h1>
        <p className="mreader-break-anywhere text-sm text-ink-400 mt-1">
          Discover → edit metadata → choose chapters → stage/edit images → publish.
        </p>
      </div>

      {resumeState === 'loading' && (
        <div className="mb-5 min-w-0 rounded-xl border border-brand-800/50 bg-brand-950/20 p-4 flex items-start gap-3">
          <Loader2
            size={18}
            className="animate-spin text-brand-400"
          />
          <div className="min-w-0">
            <div className="text-sm font-medium text-ink-200">
              Restoring active scraper draft…
            </div>
            <div className="text-xs text-ink-500 mt-1">
              Loading the persisted staging/publish state from the scraper service.
            </div>
          </div>
        </div>
      )}

      {resumeState === 'resumed' && draft && (
        <div className="mb-5 rounded-xl border border-green-900/50 bg-green-950/20 p-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-green-200">
              Resumed scraper draft
            </div>
            <div className="mreader-break-anywhere text-sm text-ink-200 mt-1">
              {draft.title || draft.slug}
            </div>
            <div className="text-xs text-ink-500 mt-1">
              Workflow detail: {draft.workflow_status}
              {publishPercent > 0 ? ` · ${publishPercent}% publish progress` : ''}
            </div>
            <div className="text-xs text-brand-300 mt-1">
              Canonical operation: {draft.operation_status ?? 'legacy/unavailable'}
              {draft.operation_phase ? ` · ${draft.operation_phase}` : ''}
            </div>
          </div>

          <div className="text-xs text-ink-500 break-all">
            Draft ID: {draft.id}
          </div>
        </div>
      )}

      {draft?.workflow_status === 'duplicate' && (
        <div className="mb-5 rounded-xl border border-amber-700/60 bg-amber-950/25 p-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-amber-200">This series already exists</div>
              <p className="mt-1 text-sm text-ink-300">
                {draft.error_message || 'An exact title/slug match already exists in the catalog. New-series scraping stopped before staging.'}
              </p>
            </div>
            {draft.duplicate_series_slug && (
              <Link
                to={`/series/${encodeURIComponent(draft.duplicate_series_slug)}`}
                className="shrink-0 inline-flex items-center justify-center gap-2 rounded-lg border border-amber-700/60 bg-amber-900/30 px-3 py-2 text-sm text-amber-100 hover:bg-amber-900/50"
              >
                Open existing series <ExternalLink size={14} />
              </Link>
            )}
          </div>
        </div>
      )}

      {draft?.published_series_id && draft.workflow_status !== 'duplicate' && (
        <div className="mb-5 rounded-xl border border-cyan-800/60 bg-cyan-950/20 p-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-cyan-200">Updating an existing series</div>
              <p className="mt-1 text-sm text-ink-300">
                Only chapter numbers missing from the production series are kept in this scrape. Existing chapter numbers are skipped again transactionally when staging, so concurrent admins cannot stage the same chapter twice.
              </p>
              {Number(draft.discovery_progress?.chapters_already_present || 0) > 0 && (
                <div className="mt-1 text-xs text-ink-500">
                  {Number(draft.discovery_progress?.chapters_already_present || 0)} already-present chapter(s) skipped during discovery.
                </div>
              )}
            </div>
            <Link
              to={`/series/${encodeURIComponent(draft.slug)}`}
              className="shrink-0 inline-flex items-center justify-center gap-2 rounded-lg border border-cyan-800/60 bg-cyan-900/25 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-900/40"
            >
              Open production series <ExternalLink size={14} />
            </Link>
          </div>
        </div>
      )}

      {draft && discoveryInFlight && (
        <div className="mb-5 rounded-xl border border-blue-800/60 bg-blue-950/20 p-4">
          <div className="flex items-start gap-3">
            <Loader2 size={18} className="animate-spin text-blue-300 mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium text-blue-200">
                  Backend series discovery is running
                </div>
                <Link
                  to="/admin/scraper/operations"
                  className="text-xs text-brand-400 hover:text-brand-300"
                >
                  View all queued/running scrapes
                </Link>
              </div>
              <div className="mreader-break-anywhere text-xs text-ink-400 mt-1">
                {discoveryProgress?.message || 'Waiting for scraper worker status…'}
              </div>
              <div className="mt-3 h-2 rounded-full bg-ink-950 border border-ink-800 overflow-hidden">
                <div
                  className="h-full bg-blue-500 transition-[width] duration-300"
                  style={{ width: `${discoveryPercent}%` }}
                />
              </div>
              <div className="flex justify-between mt-1 text-[11px] text-ink-600">
                <span>{draft.workflow_status}</span>
                <span>{discoveryPercent}%</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-5 rounded-xl border border-red-700/50 bg-red-950/30 p-4 text-red-300">
          {error}
        </div>
      )}

      <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
        <h2 className="font-display text-xl font-semibold mb-4">1. Series URL</h2>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://source.example/series/title"
            className="flex-1 px-4 py-3 bg-ink-950 border border-ink-800 rounded-xl"
          />
          <button
            onClick={discover}
            disabled={busy === 'discover' || busy === 'resume' || discoveryInFlight}
            className="px-5 py-3 sm:py-0 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {busy === 'discover' ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
            Analyze
          </button>
        </div>

        <div className="mt-4 rounded-xl border border-ink-800 bg-ink-950/60 p-4">
          <label className="flex items-center gap-2 text-sm text-ink-200 cursor-pointer">
            <input
              type="checkbox"
              checked={recursiveDiscovery}
              onChange={(e) => setRecursiveDiscovery(e.target.checked)}
            />
            Recursive same-site discovery fallback
          </label>

          <p className="text-xs text-ink-500 mt-2">
            Searches bounded same-site index/pagination links when the direct adapter does not expose all chapters.
            It never follows off-site links. Source-specific public APIs are preferred where available.
          </p>

          <div className="grid sm:grid-cols-2 gap-3 mt-3">
            <div>
              <label className="block text-xs text-ink-500 mb-1">Crawl depth</label>
              <select
                value={crawlDepth}
                disabled={!recursiveDiscovery}
                onChange={(e) => setCrawlDepth(Number(e.target.value))}
                className="w-full px-3 py-2 bg-ink-900 border border-ink-800 rounded-lg disabled:opacity-50"
              >
                <option value={0}>0 — current page only</option>
                <option value={1}>1 — recommended</option>
                <option value={2}>2 — deeper</option>
                <option value={3}>3 — maximum</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-ink-500 mb-1">Maximum pages to inspect</label>
              <input
                type="number"
                min={1}
                max={50}
                value={crawlMaxPages}
                disabled={!recursiveDiscovery}
                onChange={(e) =>
                  setCrawlMaxPages(
                    Math.max(1, Math.min(50, Number(e.target.value) || 1))
                  )
                }
                className="w-full px-3 py-2 bg-ink-900 border border-ink-800 rounded-lg disabled:opacity-50"
              />
            </div>
          </div>

          <p className="text-xs text-amber-300/80 mt-3">
            Browser challenges such as Cloudflare interstitials are reported explicitly. This crawler does not defeat access controls.
          </p>
        </div>

        {draft?.discovery && (
          <div className="mt-3 text-xs text-ink-500 flex flex-wrap gap-x-4 gap-y-1">
            <span>Strategy: {draft.discovery.source_strategy || draft.adapter}</span>
            {draft.discovery.recursive && (
              <>
                <span>Pages inspected: {draft.discovery.recursive.pages_fetched ?? 0}</span>
                <span>Recursive chapters found: {draft.discovery.recursive.chapters_found ?? 0}</span>
              </>
            )}
          </div>
        )}
      </section>

      {draft && (
        <>
          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <div className="flex flex-wrap justify-between gap-3 mb-4">
              <div>
                <h2 className="font-display text-xl font-semibold">2. Edit series metadata</h2>
                <p className="text-sm text-ink-500">{draft.adapter}</p>
              </div>
              <button
                onClick={refresh}
                className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm"
              >
                Refresh
              </button>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-ink-400">Title</label>
                <input
                  value={title}
                  disabled={!editableWorkflow}
                  onChange={(e) => {
                    const value = e.target.value;
                    setTitle(value);
                    if (!seriesSlugTouched || !slug) {
                      setSlug(kebabCase(value));
                    }
                  }}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                />
              </div>
              <div>
                <label className="text-sm text-ink-400">Slug</label>
                <input
                  value={slug}
                  disabled={!editableWorkflow}
                  onChange={(e) => {
                    setSeriesSlugTouched(true);
                    setSlug(e.target.value);
                  }}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                />
                <p className="text-xs text-ink-500 mt-1">Editing the series title automatically fills this slug in kebab-case until you edit the slug manually.</p>
              </div>
              <div>
                <label className="text-sm text-ink-400">Status</label>
                <select
                  value={seriesStatus}
                  disabled={!editableWorkflow}
                  onChange={(e) => setSeriesStatus(e.target.value)}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                >
                  <option value="ongoing">Ongoing</option>
                  <option value="completed">Completed</option>
                  <option value="hiatus">Hiatus</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              <div>
                <label className="text-sm text-ink-400">Genres (comma-separated)</label>
                <input
                  value={genres}
                  disabled={!editableWorkflow}
                  onChange={(e) => setGenres(e.target.value)}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                />
              </div>
              <div className="md:col-span-2">
                <label className="text-sm text-ink-400">Tags (comma-separated)</label>
                <input
                  value={tags}
                  disabled={!editableWorkflow}
                  onChange={(e) => setTags(e.target.value)}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                />
              </div>
              <div className="md:col-span-2">
                <label className="text-sm text-ink-400">Description</label>
                <textarea
                  value={description}
                  disabled={!editableWorkflow}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={6}
                  className="w-full mt-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800"
                />
              </div>
            </div>

            <button
              onClick={saveMetadata}
              disabled={busy === 'metadata' || !editableWorkflow}
              className="mt-4 px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50"
            >
              {editableWorkflow
                ? 'Save metadata draft'
                : `Metadata locked while status is ${draft.workflow_status}`}
            </button>
          </section>

          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <h2 className="font-display text-xl font-semibold mb-4">3. Cover</h2>

            <div className="grid md:grid-cols-[220px_1fr] gap-5">
              <div className="aspect-[3/4] bg-black rounded-xl overflow-hidden border border-ink-800 flex items-center justify-center">
                {draft.cover_staging_path ? (
                  <img
                    src={`/api/scraper/series-drafts/${draft.id}/cover/preview`}
                    className="max-w-full max-h-full object-contain"
                    alt="Draft cover"
                  />
                ) : (
                  <span className="text-ink-600 text-sm">No cover</span>
                )}
              </div>

              <div className="space-y-4">
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    value={coverUrl}
                    disabled={!editableWorkflow || busy.startsWith('cover')}
                    onChange={(e) => setCoverUrl(e.target.value)}
                    placeholder="Replacement cover URL"
                    className="flex-1 px-4 py-3 rounded-xl bg-ink-950 border border-ink-800 disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                  <button
                    onClick={replaceCover}
                    disabled={!editableWorkflow || busy.startsWith('cover')}
                    className="px-4 py-2 sm:py-0 rounded-xl bg-ink-800 hover:bg-ink-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Replace URL
                  </button>
                </div>

                <label className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-ink-800 ${
                  editableWorkflow && !busy.startsWith('cover')
                    ? 'hover:bg-ink-700 cursor-pointer'
                    : 'opacity-50 cursor-not-allowed'
                }`}>
                  <ImagePlus size={17} />
                  Upload local cover
                  <input
                    type="file"
                    accept="image/*"
                    disabled={!editableWorkflow || busy.startsWith('cover')}
                    className="hidden"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setBusy('cover-upload');
                      try {
                        loadDraft(await api.scraperUploadSeriesCover(draft.id, file));
                      } finally {
                        setBusy('');
                      }
                    }}
                  />
                </label>

                <button
                  onClick={async () => {
                    loadDraft(await api.scraperRemoveSeriesCover(draft.id));
                  }}
                  disabled={!editableWorkflow || busy.startsWith('cover')}
                  className="px-4 py-2 rounded-lg bg-red-950 text-red-300 hover:bg-red-900 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Remove cover
                </button>

                {!editableWorkflow && (
                  <p className="text-xs text-amber-300/90">
                    Cover editing is locked while a staging/publish operation owns this draft or production publication has begun.
                  </p>
                )}
              </div>
            </div>
          </section>

          <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="font-display text-xl font-semibold">4. Review chapters</h2>
                <p className="text-sm text-ink-500">
                  {selected.length} selected / {draft.chapters.length} discovered.
                </p>
              </div>

              <button
                onClick={stageSelected}
                disabled={
                  busy === 'stage' ||
                  !stageableWorkflow ||
                  selectedNeedStageCount === 0
                }
                className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50"
              >
                {draft.workflow_status === 'staging'
                  ? 'Staging in progress…'
                  : selectedNeedStageCount > 0
                    ? `Stage ${selectedNeedStageCount} selected chapter${selectedNeedStageCount === 1 ? '' : 's'}`
                    : 'Selected chapters are staged'}
              </button>
            </div>

            <div className="mb-4 grid sm:grid-cols-4 gap-3 text-sm">
              <div className="rounded-xl border border-ink-800 bg-ink-950 p-3">
                <div className="text-xl font-semibold">{selected.length}</div>
                <div className="text-xs text-ink-500 mt-1">Selected</div>
              </div>
              <div className="rounded-xl border border-green-900/50 bg-green-950/20 p-3">
                <div className="text-xl font-semibold text-green-300">
                  {selectedReadyCount}
                </div>
                <div className="text-xs text-ink-500 mt-1">Ready</div>
              </div>
              <div className="rounded-xl border border-brand-900/50 bg-brand-950/20 p-3">
                <div className="text-xl font-semibold text-brand-300">
                  {selectedPendingCount}
                </div>
                <div className="text-xs text-ink-500 mt-1">Queued / staging</div>
              </div>
              <div className="rounded-xl border border-red-900/50 bg-red-950/20 p-3">
                <div className="text-xl font-semibold text-red-300">
                  {selectedFailedCount}
                </div>
                <div className="text-xs text-ink-500 mt-1">Failed</div>
              </div>
            </div>

            {draft.workflow_status === 'staging' && (
              <div className="mb-4 rounded-xl border border-brand-800/50 bg-brand-950/20 p-4 flex items-center gap-3">
                <Loader2 size={18} className="animate-spin text-brand-400" />
                <div>
                  <div className="text-sm font-medium">
                    Staging selected chapters…
                  </div>
                  <div className="text-xs text-ink-500 mt-1">
                    This page refreshes worker status automatically every 2 seconds.
                    Ready chapters can publish immediately; failed chapters can be retried independently.
                  </div>
                </div>
              </div>
            )}

            {draft.workflow_status === 'failed' && (
              <div className="mb-4 rounded-xl border border-amber-800/50 bg-amber-950/20 p-4 text-sm text-amber-100">
                One or more chapters failed staging. You can retry those chapters,
                or publish the chapters that are already ready; failed staging
                chapters will be skipped and recorded instead of blocking the batch.
              </div>
            )}

            <div className="hidden md:grid md:grid-cols-[40px_90px_180px_minmax(0,1fr)_130px_190px] gap-2 items-center px-3 pb-2 text-[11px] uppercase tracking-wide text-ink-600">
              <span>Use</span>
              <span>Number</span>
              <span title="Automatically generated from chapter number">Slug (auto)</span>
              <span className="flex items-center justify-between gap-2">
                <span>Chapter title</span>
                <button
                  type="button"
                  onClick={clearAllChapterTitles}
                  disabled={
                    !chapterTitleClearAllowed ||
                    busy === 'clear-chapter-titles' ||
                    (chapterTitlesSuppressed &&
                      !draft.chapters.some((chapter) =>
                        Boolean(chapter.chapter_title?.trim())
                      ))
                  }
                  className="normal-case tracking-normal text-[10px] px-2 py-1 rounded-md border border-red-900/70 bg-red-950/30 text-red-300 hover:bg-red-950 disabled:opacity-40 disabled:cursor-not-allowed"
                  title="Clear current chapter titles and keep newly discovered chapters untitled for this scrape. Chapter numbers and generated slugs are preserved."
                >
                  {busy === 'clear-chapter-titles'
                    ? 'Clearing…'
                    : chapterTitlesSuppressed
                      ? 'Titles cleared'
                      : 'Clear all'}
                </button>
              </span>
              <span>Stage</span>
              <span>Publish</span>
            </div>

            {chapterTitlesSuppressed && (
              <div className="mb-2 px-3 text-xs text-green-400">
                Chapter titles are cleared for this scrape. Newly discovered update chapters will also remain untitled.
              </div>
            )}

            <div className="max-h-[500px] overflow-y-auto space-y-2">
              {draft.chapters.map((chapter) => (
                <div
                  key={chapter.id}
                  className="grid min-w-0 md:grid-cols-[40px_90px_180px_minmax(0,1fr)_130px_190px] gap-2 items-center rounded-xl border border-ink-800 bg-ink-950 p-3"
                >
                  <input
                    type="checkbox"
                    checked={chapter.selected}
                    disabled={isChapterMutationLocked(chapter)}
                    onChange={(e) =>
                      updateChapter(chapter, { selected: e.target.checked })
                    }
                  />
                  <input
                    disabled={isChapterMutationLocked(chapter)}
                    value={String(chapter.chapter_number)}
                    onChange={(e) => {
                      const chapterNumber = e.target.value;
                      previewChapterPatch(chapter.id, {
                        chapter_number: chapterNumber,
                        chapter_slug: chapterSlugFromNumber(chapterNumber),
                      });
                    }}
                    onBlur={(e) => {
                      const chapterNumber = e.target.value;
                      void updateChapter(chapter, {
                        chapter_number: chapterNumber,
                        chapter_slug: chapterSlugFromNumber(chapterNumber),
                      });
                    }}
                    className="px-2 py-2 rounded bg-ink-900 border border-ink-800"
                  />
                  <input
                    value={chapter.chapter_slug}
                    readOnly
                    tabIndex={-1}
                    title="Automatically generated from the chapter number"
                    className="px-2 py-2 rounded bg-ink-900/70 border border-ink-800 text-ink-400 cursor-default"
                  />
                  <input
                    value={chapter.chapter_title || ''}
                    disabled={isChapterMutationLocked(chapter)}
                    onChange={(e) => {
                      const chapterTitle = e.target.value;
                      previewChapterPatch(chapter.id, {
                        chapter_title: chapterTitle || null,
                      });
                    }}
                    onBlur={(e) =>
                      updateChapter(chapter, {
                        chapter_title: e.target.value.trim() || null,
                        chapter_slug: chapter.chapter_slug,
                      })
                    }
                    placeholder="Optional chapter title"
                    className="px-2 py-2 rounded bg-ink-900 border border-ink-800"
                  />
                  <div className="flex flex-col gap-1">
                    <button
                      onClick={() => {
                        if (chapter.stage_status === 'error' || chapter.stage_status === 'discovered') {
                          void stageOneChapter(chapter);
                          return;
                        }
                        setExpandedChapterId(chapter.id);
                        writeStoredValue(
                          EXPANDED_CHAPTER_STORAGE_KEY,
                          chapter.id
                        );
                      }}
                      disabled={
                        busy === `stage-chapter:${chapter.id}` ||
                        ['queued', 'staging', 'published'].includes(chapter.stage_status) ||
                        ((chapter.stage_status === 'error' || chapter.stage_status === 'discovered') &&
                          (!stageableWorkflow || chapterEditingLocked))
                      }
                      className={`px-3 py-2 rounded-lg text-sm disabled:opacity-60 ${
                        chapter.stage_status === 'ready'
                          ? 'bg-green-950 text-green-300'
                          : chapter.stage_status === 'error'
                            ? 'bg-red-950 text-red-300'
                            : 'bg-ink-800'
                      }`}
                      title={chapter.error_message || chapter.stage_status}
                    >
                      {busy === `stage-chapter:${chapter.id}`
                        ? 'Queuing…'
                        : chapter.stage_status === 'error'
                          ? 'Retry stage'
                          : chapter.stage_status === 'ready'
                            ? `Ready (${chapter.pages.length})`
                            : chapter.stage_status}
                    </button>
                  </div>
                  <div
                    className={`px-2 py-2 rounded-lg text-xs border ${
                      chapter.published_chapter_id ||
                      chapter.publish_status === 'published'
                        ? 'bg-green-950/40 border-green-900 text-green-300'
                        : chapter.publish_status === 'failed'
                          ? 'bg-red-950/40 border-red-900 text-red-300'
                          : chapter.publish_status === 'skipped'
                            ? 'bg-amber-950/40 border-amber-900 text-amber-300'
                            : chapter.publish_status === 'cancelled'
                              ? 'bg-ink-900 border-ink-700 text-ink-300'
                              : ['pending', 'publishing'].includes(chapter.publish_status)
                                ? 'bg-brand-950/40 border-brand-900 text-brand-300'
                                : 'bg-ink-900 border-ink-800 text-ink-500'
                    }`}
                    title={
                      chapter.publish_error ||
                      chapter.publish_progress?.message ||
                      chapter.publish_status
                    }
                  >
                    {chapter.published_chapter_id || chapter.publish_status === 'published' ? (
                      <div className="flex items-center gap-1.5 font-medium">
                        <CheckCircle2 size={14} />
                        Published
                      </div>
                    ) : ['pending', 'publishing'].includes(chapter.publish_status) &&
                      chapter.publish_progress?.mode === 'single' ? (
                      <div>
                        <div className="flex items-center gap-1.5 font-medium">
                          <Loader2 size={13} className="animate-spin" />
                          {chapter.publish_status === 'publishing' ? 'Publishing' : 'Queued'}
                        </div>
                        <div className="mt-1 text-[10px]">
                          {Number(chapter.publish_progress?.percent || 0)}%
                        </div>
                      </div>
                    ) : chapter.stage_status === 'ready' ? (
                      <button
                        type="button"
                        onClick={() => void publishOneChapter(chapter)}
                        disabled={
                          publishInFlight ||
                          chapterEditingLocked ||
                          busy === `publish-chapter:${chapter.id}`
                        }
                        className="w-full px-2 py-1.5 rounded-md bg-brand-600 hover:bg-brand-500 text-white font-medium disabled:opacity-50"
                      >
                        {busy === `publish-chapter:${chapter.id}`
                          ? 'Queuing…'
                          : chapter.publish_status === 'failed'
                            ? 'Retry publish'
                            : 'Publish chapter'}
                      </button>
                    ) : (
                      <div className="font-medium truncate">
                        {chapter.stage_status === 'error'
                          ? 'Fix staging first'
                          : chapter.publish_status || 'Waiting'}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {expanded && expanded.stage_status === 'ready' && (
            <section className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 mb-6">
              <h2 className="font-display text-xl font-semibold mb-2">
                5. Edit {expanded.chapter_slug} images
              </h2>
              <p className="text-sm text-ink-500 mb-4">
                Remove/reorder/add pages before anything is written into the production chapter/page tables.
              </p>

              {isChapterMutationLocked(expanded) && (
                <div className="mb-4 rounded-xl border border-amber-800/50 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
                  Page editing is read-only while staging/publishing owns this chapter. This prevents the worker from publishing a stale or partially edited page set.
                </div>
              )}

              <div className="mb-4 rounded-xl border border-brand-900/40 bg-brand-950/20 px-4 py-3 text-sm text-ink-300 flex items-start gap-3">
                <GripVertical size={18} className="text-brand-400 shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium text-ink-200">Drag pages to reorder</div>
                  <div className="text-xs text-ink-500 mt-0.5">
                    Hold the left or right mouse button on a page card, move it to the desired position,
                    then release to save the order.
                  </div>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {expanded.pages.map((page, index) => (
                  <div
                    key={page.id}
                    data-page-id={page.id}
                    onPointerDown={
                      isChapterMutationLocked(expanded)
                        ? undefined
                        : (event) => expandedPageReorder.startReorder(event, page.id)
                    }
                    onPointerEnter={
                      isChapterMutationLocked(expanded)
                        ? undefined
                        : (event) => expandedPageReorder.enterReorderTarget(event, page.id)
                    }
                    onPointerUp={
                      isChapterMutationLocked(expanded)
                        ? undefined
                        : expandedPageReorder.finishReorder
                    }
                    onContextMenu={(event) => event.preventDefault()}
                    className={`rounded-xl overflow-hidden border bg-ink-950 transition-all select-none ${
                      isChapterMutationLocked(expanded)
                        ? 'cursor-default opacity-90'
                        : 'cursor-grab active:cursor-grabbing'
                    } ${
                      expandedPageReorder.draggedId === page.id
                        ? 'border-brand-400 ring-2 ring-brand-500/40 scale-[1.02] opacity-80'
                        : 'border-ink-800 hover:border-ink-600'
                    }`}
                  >
                    <div className="aspect-[3/4] bg-black flex items-center justify-center">
                      <img
                        src={`/api/scraper/series-drafts/chapters/${expanded.id}/pages/${page.id}/preview`}
                        alt={`Page ${index + 1}`}
                        className="max-w-full max-h-full object-contain"
                      />
                    </div>

                    <div className="p-3 flex items-center gap-2">
                      <span
                        className="p-2 rounded bg-brand-950/40 text-brand-400"
                        title="Hold left or right mouse button and drag"
                      >
                        <GripVertical size={14} />
                      </span>
                      <span className="text-sm flex-1">Page {index + 1}</span>
                      <button
                        onClick={() => movePage(expanded, page.id, -1)}
                        disabled={isChapterMutationLocked(expanded) || index === 0}
                        className="p-2 rounded bg-ink-800 disabled:opacity-30"
                      >
                        <ArrowUp size={14} />
                      </button>
                      <button
                        onClick={() => movePage(expanded, page.id, 1)}
                        disabled={isChapterMutationLocked(expanded) || index === expanded.pages.length - 1}
                        className="p-2 rounded bg-ink-800 disabled:opacity-30"
                      >
                        <ArrowDown size={14} />
                      </button>
                      <button
                        onClick={() => removePage(expanded.id, page.id)}
                        disabled={isChapterMutationLocked(expanded)}
                        className="p-2 rounded bg-red-950 text-red-300 disabled:opacity-30"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid md:grid-cols-2 gap-4 mt-6">
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    value={newPageUrl}
                    disabled={isChapterMutationLocked(expanded)}
                    onChange={(e) => setNewPageUrl(e.target.value)}
                    placeholder="Add missing page URL"
                    className="flex-1 px-3 py-2 rounded-lg bg-ink-950 border border-ink-800"
                  />
                  <button
                    onClick={addPageUrl}
                    disabled={isChapterMutationLocked(expanded)}
                    className="px-3 py-2 sm:py-0 rounded-lg bg-ink-800 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Add
                  </button>
                </div>

                <label className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg bg-ink-800 ${
                  isChapterMutationLocked(expanded)
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer hover:bg-ink-700'
                }`}>
                  <ImagePlus size={16} />
                  Upload missing page
                  <input
                    type="file"
                    accept="image/*"
                    disabled={isChapterMutationLocked(expanded)}
                    className="hidden"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      loadDraft(
                        await api.scraperAddSeriesDraftPageFile(
                          expanded.id,
                          file
                        )
                      );
                    }}
                  />
                </label>
              </div>
            </section>
          )}

          <section className="min-w-0 rounded-2xl border border-brand-800/50 bg-brand-950/20 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-display text-xl font-semibold">
                  6. Publish reviewed series
                </h2>
                <p className="text-sm text-ink-400 mt-1">
                  Publish is one durable series operation. Ready chapters commit independently while the
                  coordinator waits for selected chapters that are still staging, so large scrapes do not
                  require manual Publish clicks per chapter. Browser refresh does not own or cancel the worker job.
                </p>
              </div>

              <div className="flex flex-wrap gap-2 justify-end">
                <button
                  onClick={publish}
                  disabled={
                    busy === 'publish' ||
                    !canPublish ||
                    publishInFlight ||
                    draft.workflow_status === 'published'
                  }
                  className="px-6 py-3 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 flex items-center gap-2"
                >
                  {publishInFlight ? (
                    <>
                      <Loader2 size={17} className="animate-spin" />
                      Publishing {publishPercent}%
                    </>
                  ) : draft.workflow_status === 'published' ? (
                    'Published'
                  ) : draft.workflow_status === 'published_partial' ? (
                    selectedPublishableCount > 0
                      ? `Retry ${selectedPublishableCount} chapter${selectedPublishableCount === 1 ? '' : 's'}${selectedPendingCount ? ` + wait for ${selectedPendingCount}` : ''}`
                      : 'Partially published'
                  ) : draft.workflow_status === 'cancelled' ? (
                    selectedPublishableCount > 0
                      ? 'Resume Publish'
                      : 'Cancelled'
                  ) : canPublish ? (
                    selectedFailedCount > 0
                      ? `Publish ${selectedPublishableCount}; wait ${selectedPendingCount}; skip ${selectedFailedCount}`
                      : selectedPendingCount > 0
                        ? `Publish ${selectedPublishableCount} ready + wait for ${selectedPendingCount}`
                        : `Publish ${selectedPublishableCount} chapter${selectedPublishableCount === 1 ? '' : 's'}`
                  ) : (
                    'No selected chapters to publish'
                  )}
                </button>

                {publishInFlight && (
                  <button
                    type="button"
                    onClick={cancelPublish}
                    disabled={busy === 'cancel-publish'}
                    className="px-4 py-3 rounded-xl bg-red-950 hover:bg-red-900 border border-red-800 text-red-200 disabled:opacity-50"
                  >
                    {busy === 'cancel-publish'
                      ? 'Requesting cancel…'
                      : 'Cancel publish'}
                  </button>
                )}
              </div>
            </div>

            {(publishInFlight || publishFinished || publishFailed || publishPercent > 0) && (
              <div className="mt-5 rounded-2xl border border-ink-800 bg-ink-950/70 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-sm text-ink-500">Publish progress</div>
                    <div className="font-display text-2xl font-semibold mt-1">
                      {publishPercent}%
                    </div>
                  </div>

                  <div
                    className={`px-3 py-1 rounded-full text-xs ${
                      publishFailed
                        ? 'bg-red-950 text-red-300 border border-red-800'
                        : publishCancelled
                          ? 'bg-ink-900 text-ink-300 border border-ink-700'
                          : publishPartial
                            ? 'bg-amber-950 text-amber-300 border border-amber-800'
                            : verificationWarning
                          ? 'bg-amber-950 text-amber-300 border border-amber-800'
                          : publishFinished
                            ? 'bg-green-950 text-green-300 border border-green-800'
                            : 'bg-brand-950 text-brand-300 border border-brand-800'
                    }`}
                  >
                    {publishProgress?.phase || draft.workflow_status}
                  </div>
                </div>

                <div className="mt-4 h-3 rounded-full bg-ink-800 overflow-hidden">
                  <div
                    className="h-full bg-brand-500 transition-[width] duration-500"
                    style={{ width: `${publishPercent}%` }}
                  />
                </div>

                <div className="mt-3 flex items-start gap-3 text-sm">
                  {publishInFlight ? (
                    <Loader2 size={17} className="animate-spin text-brand-400 shrink-0 mt-0.5" />
                  ) : publishFailed || verificationWarning || publishPartial ? (
                    <AlertTriangle size={17} className="text-amber-400 shrink-0 mt-0.5" />
                  ) : publishCancelled ? (
                    <AlertTriangle size={17} className="text-ink-400 shrink-0 mt-0.5" />
                  ) : (
                    <CheckCircle2 size={17} className="text-green-400 shrink-0 mt-0.5" />
                  )}
                  <div>
                    <div className="text-ink-200">
                      {publishProgress?.message || 'Waiting for publish status…'}
                    </div>

                    {publishProgress?.current_chapter_slug && (
                      <div className="text-xs text-ink-500 mt-1">
                        Current chapter: {publishProgress.current_chapter_slug}
                        {publishProgress.current_page
                          ? ` · source page ${publishProgress.current_page}`
                          : ''}
                      </div>
                    )}
                  </div>
                </div>

                <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
                  <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                    <div className="text-lg font-semibold">
                      {terminalChapterCount}/
                      {publishProgress?.total_chapters ?? selected.length}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">
                      Chapter outcomes complete
                    </div>
                    <div className="text-[11px] text-ink-600 mt-1">
                      {chapterPublishCounts.published} published · {chapterPublishCounts.publishing} publishing · {selectedPendingCount} staging
                    </div>
                  </div>

                  <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                    <div className="text-lg font-semibold">
                      {publishProgress?.source_pages_completed ?? 0}/
                      {publishProgress?.total_source_pages ?? 0}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">
                      Source pages processed
                    </div>
                    <div className="text-[11px] text-ink-600 mt-1">Live total recalculated as staging finishes</div>
                  </div>

                  <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                    <div className="text-lg font-semibold">
                      {publishProgress?.final_pages_written ?? 0}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">
                      Live reader pages written
                    </div>
                    <div className="text-[11px] text-ink-600 mt-1">May exceed source pages when one source is split; failed outputs are excluded after cleanup</div>
                  </div>

                  <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                    <div className="text-lg font-semibold">
                      Attempt {draft.publish_attempt || 0}
                    </div>
                    <div className="text-xs text-ink-500 mt-1">
                      Idempotent publish attempt
                    </div>
                  </div>
                </div>

                <div className="mt-5">
                  <div className="text-sm font-medium mb-3">
                    Chapter publish results
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="rounded-xl border border-green-900/50 bg-green-950/20 p-3">
                      <div className="text-lg font-semibold text-green-300">
                        {chapterPublishCounts.published}
                      </div>
                      <div className="text-xs text-ink-500 mt-1">Published</div>
                    </div>
                    <div className="rounded-xl border border-red-900/50 bg-red-950/20 p-3">
                      <div className="text-lg font-semibold text-red-300">
                        {chapterPublishCounts.failed}
                      </div>
                      <div className="text-xs text-ink-500 mt-1">Failed</div>
                    </div>
                    <div className="rounded-xl border border-amber-900/50 bg-amber-950/20 p-3">
                      <div className="text-lg font-semibold text-amber-300">
                        {chapterPublishCounts.skipped}
                      </div>
                      <div className="text-xs text-ink-500 mt-1">Skipped</div>
                    </div>
                    <div className="rounded-xl border border-ink-700 bg-ink-900/60 p-3">
                      <div className="text-lg font-semibold text-ink-300">
                        {chapterPublishCounts.cancelled}
                      </div>
                      <div className="text-xs text-ink-500 mt-1">Cancelled</div>
                    </div>
                  </div>
                </div>

                {(publishFinished ||
                  publishProgress?.phase === 'verifying_catalog' ||
                  publishProgress?.phase === 'verifying_reader') && (
                  <div className="mt-5">
                    <div className="text-sm font-medium mb-3">
                      Production availability checks
                    </div>

                    <div className="grid sm:grid-cols-3 gap-3">
                      <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                        <div
                          className={
                            publishProgress?.catalog_verified
                              ? 'text-green-300'
                              : 'text-amber-300'
                          }
                        >
                          {publishProgress?.catalog_verified ? 'Verified' : 'Checking'}
                        </div>
                        <div className="text-xs text-ink-500 mt-1">
                          Catalog series
                        </div>
                        <div className="text-xs text-ink-400 mt-1">
                          {publishProgress?.catalog_verified_chapters ?? 0}/
                          {publishProgress?.total_chapters ?? selected.length} chapter endpoints
                        </div>
                      </div>

                      <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                        <div className="text-green-300">
                          {publishProgress?.reader_verified_chapters ?? 0}/
                          {publishProgress?.total_chapters ?? selected.length}
                        </div>
                        <div className="text-xs text-ink-500 mt-1">
                          Reader chapter manifests
                        </div>
                      </div>

                      <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                        <div className="text-green-300">
                          {publishProgress?.reader_verified_images ?? 0}/
                          {publishProgress?.total_chapters ?? selected.length}
                        </div>
                        <div className="text-xs text-ink-500 mt-1">
                          Reader first-page image checks
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {!!publishProgress?.verification_errors?.length && (
                  <div className="mt-5 rounded-xl border border-amber-900/60 bg-amber-950/20 p-4">
                    <div className="flex items-center gap-2 text-amber-200 font-medium">
                      <AlertTriangle size={17} />
                      Publish / verification issues
                    </div>
                    <div className="mt-3 space-y-2 max-h-48 overflow-y-auto">
                      {publishProgress.verification_errors.map((message, index) => (
                        <div
                          key={`${index}:${message}`}
                          className="text-xs text-amber-100/80 break-words"
                        >
                          {index + 1}. {message}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {publishFinished && draft.published_series_id && (
                  <div className="mt-5 flex flex-wrap gap-3">
                    <Link
                      to={`/series/${draft.slug}`}
                      className="px-4 py-2 rounded-xl bg-green-900/40 hover:bg-green-900/70 border border-green-800 text-green-200 text-sm flex items-center gap-2"
                    >
                      <ExternalLink size={16} />
                      Open in Catalog
                    </Link>

                    {selected[0] && (
                      <Link
                        to={`/read/${draft.slug}/${selected[0].chapter_slug}`}
                        className="px-4 py-2 rounded-xl bg-brand-900/40 hover:bg-brand-900/70 border border-brand-800 text-brand-200 text-sm flex items-center gap-2"
                      >
                        <BookOpen size={16} />
                        Read first published chapter
                      </Link>
                    )}
                  </div>
                )}

                {publishInFlight && (
                  <div className="mt-4 text-xs text-ink-500">
                    The publish worker is independent of this browser. Refreshing,
                    closing, or reopening this page does not cancel the job. Only the
                    explicit Cancel publish action requests a stop. Duplicate publish
                    requests and recovered queue messages are protected by a database lock.
                  </div>
                )}
              </div>
            )}

            {(flowEvents.length > 0 || flowError) && (
              <div className="mt-5 rounded-2xl border border-ink-800 bg-ink-950/70 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-display text-lg font-semibold">End-to-end data flow</div>
                    <div className="text-xs text-ink-500 mt-1">
                      Correlated operation timeline across API, RabbitMQ, workers, publish phases and verification.
                    </div>
                  </div>
                  <span className="text-xs text-ink-500">{flowTotal} events · showing {flowEvents.length}</span>
                </div>
                {flowError && (
                  <div className="mt-3 rounded-xl border border-red-900/60 bg-red-950/20 p-3 text-xs text-red-200">
                    Data-flow observability error: {flowError}
                  </div>
                )}
                {!!flowEvents.length && (
                  <div className="mt-4 max-h-80 overflow-y-auto space-y-2">
                    {flowEvents.map((event) => (
                      <div key={event.id} className="rounded-xl border border-ink-800 bg-ink-900/60 p-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="font-medium text-brand-300">{event.service}</span>
                          <span className="text-ink-500">{event.event_type}</span>
                          {event.phase && <span className="text-ink-300">· {event.phase}</span>}
                          {event.status && <span className="text-ink-500">· {event.status}</span>}
                          <span className="ml-auto text-ink-600">{new Date(event.created_at).toLocaleTimeString()}</span>
                        </div>
                        <div className="mt-1 text-sm text-ink-200 break-words">{event.message}</div>
                        {(event.chapter_id || event.request_id) && (
                          <div className="mt-1 text-[11px] text-ink-600 break-all">
                            {event.chapter_id ? `chapter ${event.chapter_id}` : ''}
                            {event.chapter_id && event.request_id ? ' · ' : ''}
                            {event.request_id ? `request ${event.request_id}` : ''}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {flowNextBeforeId && flowEvents.length < flowTotal && (
                  <button
                    type="button"
                    onClick={() => void loadOlderFlowEvents()}
                    disabled={flowLoadingOlder}
                    className="mt-3 rounded-xl border border-ink-700 px-3 py-2 text-xs text-ink-200 hover:border-brand-600 disabled:opacity-50"
                  >
                    {flowLoadingOlder ? 'Loading older events…' : `Load older events (${Math.max(0, flowTotal - flowEvents.length)} remaining)`}
                  </button>
                )}
              </div>
            )}

            <div className="mt-4 space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                {draft.workflow_status === 'published' && (
                  <CheckCircle2 size={17} className="text-green-400" />
                )}
                {draft.workflow_status === 'published_partial' && (
                  <AlertTriangle size={17} className="text-amber-400" />
                )}
                {workflowBusy && (
                  <Loader2 size={16} className="animate-spin text-brand-400" />
                )}
                <span>Workflow detail: {draft.workflow_status}</span>
                <span className="text-brand-300">
                  Canonical operation: {draft.operation_status ?? 'legacy/unavailable'}
                  {draft.operation_phase ? ` · ${draft.operation_phase}` : ''}
                </span>
                <span className="text-ink-500">
                  · {selectedReadyCount}/{selected.length} selected chapters ready
                </span>
              </div>

              {!canPublish &&
                ![
                  'queued_publish',
                  'publishing',
                  'published',
                  'published_partial',
                  'cancelled',
                ].includes(draft.workflow_status) && (
                  <div className="text-xs text-amber-300">
                    Batch publish waits for active staging, but any chapter already marked Ready can be published from its own row above.
                  </div>
                )}

              {draft.error_message && (
                <div className="mreader-break-anywhere text-red-300">
                  {draft.error_message}
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
