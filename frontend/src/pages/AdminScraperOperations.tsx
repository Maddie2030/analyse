import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Loader2,
  RefreshCw,
  RotateCcw,
  ServerCog,
  Trash2,
} from 'lucide-react';
import {
  api,
  type ScraperOperation,
  type ScraperOperationsResponse,
} from '../api/client';

type Filter =
  | 'unacknowledged'
  | 'running'
  | 'awaiting_admin'
  | 'completed'
  | 'attention'
  | 'all';

const filters: Array<{ key: Filter; label: string }> = [
  { key: 'unacknowledged', label: 'Open' },
  { key: 'running', label: 'Running' },
  { key: 'awaiting_admin', label: 'Needs review' },
  { key: 'completed', label: 'Completed' },
  { key: 'attention', label: 'Attention' },
  { key: 'all', label: 'All' },
];

const emptyResponse: ScraperOperationsResponse = {
  items: [],
  summary: {
    running: 0,
    awaiting_admin: 0,
    completed: 0,
    attention: 0,
    acknowledged: 0,
    total: 0,
  },
  queue_depths: {
    discovery: null,
    staging: null,
    publish: null,
  },
};

function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function statusTone(group: ScraperOperation['operation_group']) {
  switch (group) {
    case 'running':
      return 'border-blue-800/60 bg-blue-950/20 text-blue-200';
    case 'awaiting_admin':
      return 'border-amber-800/60 bg-amber-950/20 text-amber-200';
    case 'completed':
      return 'border-green-800/60 bg-green-950/20 text-green-200';
    case 'attention':
      return 'border-red-800/60 bg-red-950/20 text-red-200';
    default:
      return 'border-ink-700 bg-ink-900 text-ink-300';
  }
}

function groupLabel(group: ScraperOperation['operation_group']) {
  switch (group) {
    case 'running': return 'Running';
    case 'awaiting_admin': return 'Needs admin review';
    case 'completed': return 'Backend confirmed complete';
    case 'attention': return 'Needs attention';
    default: return 'Unknown';
  }
}

function progressPercent(operation: ScraperOperation) {
  return Math.max(0, Math.min(100, Number(operation.progress?.percent ?? 0)));
}

export default function AdminScraperOperations() {
  const [filter, setFilter] = useState<Filter>('unacknowledged');
  const [data, setData] = useState<ScraperOperationsResponse>(emptyResponse);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [error, setError] = useState('');
  const loadRequestRef = useRef(0);

  const load = useCallback(async (quiet = false) => {
    const requestId = ++loadRequestRef.current;
    if (!quiet) setRefreshing(true);
    try {
      const result = await api.scraperListOperations(filter, 300);
      if (requestId !== loadRequestRef.current) return;
      setData(result);
      setError('');
    } catch (err: any) {
      if (requestId !== loadRequestRef.current) return;
      setError(
        err?.detail || err?.message || 'Failed to load scraper operations.'
      );
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
      if (requestId === loadRequestRef.current && !quiet) setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    void load(true);
  }, [load]);

  useEffect(() => {
    const interval = data.summary.running > 0 ? 1500 : 7000;
    const timer = window.setInterval(() => {
      void load(true);
    }, interval);
    return () => window.clearInterval(timer);
  }, [load, data.summary.running]);

  const counts = useMemo(() => ({
    running: data.summary.running,
    awaiting_admin: data.summary.awaiting_admin,
    completed: data.summary.completed,
    attention: data.summary.attention,
  }), [data.summary]);

  const acknowledge = async (operation: ScraperOperation) => {
    setBusyId(operation.id);
    setError('');
    setData((current) => ({
      ...current,
      items: current.items.filter((item) => item.id !== operation.id),
    }));
    try {
      await api.scraperAcknowledgeOperation(operation.id);
      await load(true);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Failed to acknowledge operation.');
      await load(true);
    } finally {
      setBusyId('');
    }
  };

  const retryDiscovery = async (operation: ScraperOperation) => {
    setBusyId(operation.id);
    setError('');
    try {
      await api.scraperRetryDiscovery(operation.id);
      setFilter('unacknowledged');
      await load(true);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Failed to retry discovery.');
    } finally {
      setBusyId('');
    }
  };

  const cancelOperation = async (operation: ScraperOperation) => {
    const active = operation.operation_group === 'running';
    const confirmed = window.confirm(
      active
        ? 'Cancel this scraper task? Queued work will be removed immediately and any active backend worker will stop at the next safe boundary. Private staging for this operation will be deleted; already published production chapters will not be removed.'
        : 'Remove this scraper operation from Scrape Ops? Private staging owned by this operation will be deleted. Already published production content will not be removed.'
    );
    if (!confirmed) return;

    setBusyId(operation.id);
    setError('');
    // Remove it from the visible dashboard immediately; the backend keeps a
    // durable cancel marker until any active worker has stopped and cleanup ends.
    setData((current) => ({
      ...current,
      items: current.items.filter((item) => item.id !== operation.id),
    }));
    try {
      await api.scraperCancelOperation(operation.id);
      await load(true);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Failed to cancel scraper operation.');
      await load(true);
    } finally {
      setBusyId('');
    }
  };

  return (
    <div className="w-full min-w-0 max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-brand-400 mb-2">
            <Activity size={19} />
            <span className="text-sm font-medium">Persistent queue monitor</span>
          </div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold">
            Scrape Operations
          </h1>
          <p className="text-sm text-ink-400 mt-1 max-w-3xl">
            Backend-owned status for every new-series scrape, staging run, and publish job.
            Refreshing the browser does not lose jobs. Acknowledging a terminal operation clears
            it from this dashboard and removes only its private scraper staging residue.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Link
            to="/admin/scraper/new-series"
            className="px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-sm font-medium"
          >
            New series scrape
          </Link>
          <button
            type="button"
            onClick={() => void load(false)}
            disabled={refreshing}
            className="px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm flex items-center gap-2 disabled:opacity-50"
          >
            <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-5 rounded-xl border border-red-800/60 bg-red-950/30 p-4 text-red-200">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-5">
        <Metric label="Running" value={data.summary.running} icon={<Loader2 size={16} className={data.summary.running ? 'animate-spin' : ''} />} />
        <Metric label="Needs review" value={data.summary.awaiting_admin} icon={<Clock3 size={16} />} />
        <Metric label="Completed" value={data.summary.completed} icon={<CheckCircle2 size={16} />} />
        <Metric label="Attention" value={data.summary.attention} icon={<AlertTriangle size={16} />} />
        <Metric label="All tracked" value={data.summary.total} icon={<ServerCog size={16} />} />
      </div>

      <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3 sm:p-4 mb-5">
        <div className="text-xs uppercase tracking-wide text-ink-500 mb-2">Queue depth</div>
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <span>Discovery <strong className="text-ink-100">{data.queue_depths.discovery ?? '—'}</strong></span>
          <span>Staging <strong className="text-ink-100">{data.queue_depths.staging ?? '—'}</strong></span>
          <span>Publish <strong className="text-ink-100">{data.queue_depths.publish ?? '—'}</strong></span>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-2 mb-4">
        {filters.map((item) => {
          const count = item.key in counts ? counts[item.key as keyof typeof counts] : undefined;
          return (
            <button
              type="button"
              key={item.key}
              onClick={() => setFilter(item.key)}
              className={`whitespace-nowrap px-3 py-2 rounded-lg text-sm border transition-colors ${
                filter === item.key
                  ? 'border-brand-600 bg-brand-600/15 text-brand-300'
                  : 'border-ink-800 bg-ink-900 text-ink-400 hover:text-ink-100'
              }`}
            >
              {item.label}{count !== undefined ? ` (${count})` : ''}
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="rounded-2xl border border-ink-800 bg-ink-900/60 p-10 text-center text-ink-400">
          <Loader2 className="animate-spin mx-auto mb-3" size={24} />
          Loading persistent scraper operations…
        </div>
      ) : data.items.length === 0 ? (
        <div className="rounded-2xl border border-ink-800 bg-ink-900/60 p-10 text-center text-ink-500">
          No operations match this view.
        </div>
      ) : (
        <div className="space-y-3">
          {data.items.map((operation) => {
            const percent = progressPercent(operation);
            const discoveryFailed =
              operation.workflow_status === 'failed' &&
              operation.discovery_progress?.phase === 'failed';
            const canAcknowledge = ['completed', 'attention'].includes(operation.operation_group);
            const isBusy = busyId === operation.id;

            return (
              <article
                key={operation.id}
                className="min-w-0 rounded-2xl border border-ink-800 bg-ink-900/70 p-4 sm:p-5"
              >
                <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 mb-2">
                      <span className={`px-2.5 py-1 rounded-full border text-xs font-medium ${statusTone(operation.operation_group)}`}>
                        {groupLabel(operation.operation_group)}
                      </span>
                      <span className="px-2.5 py-1 rounded-full border border-ink-700 bg-ink-950 text-xs text-ink-400">
                        Workflow detail: {operation.workflow_status}
                      </span>
                      <span className="px-2.5 py-1 rounded-full border border-brand-800/60 bg-brand-950/20 text-xs text-brand-200">
                        Canonical operation: {operation.operation_status ?? 'legacy/unavailable'}
                        {operation.operation_phase ? ` · ${operation.operation_phase}` : ''}
                      </span>
                      {operation.queue_name && (
                        <span className="text-xs text-ink-500">
                          {operation.queue_name} queue{operation.queue_position ? ` #${operation.queue_position}` : ''}
                        </span>
                      )}
                    </div>

                    <h2 className="mreader-break-anywhere font-display text-lg font-semibold">
                      {operation.title || operation.slug || 'Pending series discovery'}
                    </h2>
                    <div className="mreader-break-anywhere text-xs text-ink-500 mt-1">
                      {operation.source_url}
                    </div>

                    {operation.workflow_status === 'duplicate' && operation.duplicate_series_slug && (
                      <Link
                        to={`/series/${encodeURIComponent(operation.duplicate_series_slug)}`}
                        className="mt-2 inline-flex items-center gap-1.5 text-sm text-amber-300 hover:text-amber-200"
                      >
                        Existing series: {operation.duplicate_series_title || operation.duplicate_series_slug}
                        <ExternalLink size={13} />
                      </Link>
                    )}

                    <div className="mt-4">
                      <div className="flex items-center justify-between gap-3 text-xs mb-1.5">
                        <span className="text-ink-300">
                          {String(operation.progress?.message || operation.workflow_status)}
                        </span>
                        <span className="text-ink-500 shrink-0">{percent}%</span>
                      </div>
                      <div className="h-2 rounded-full bg-ink-950 overflow-hidden border border-ink-800">
                        <div
                          className="h-full bg-brand-500 transition-[width] duration-300"
                          style={{ width: `${percent}%` }}
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 text-xs">
                      <Info label="Chapters" value={operation.chapter_count} />
                      <Info label="Staged" value={`${operation.ready_chapters}/${operation.selected_chapters}`} />
                      <Info label="Published" value={operation.published_chapters} />
                      <Info label="Updated" value={formatDate(operation.updated_at)} />
                    </div>

                    {operation.error_message && (
                      <div className="mt-4 rounded-lg border border-red-900/60 bg-red-950/20 p-3 text-sm text-red-300 break-words">
                        {operation.error_message}
                      </div>
                    )}
                  </div>

                  <div className="flex lg:w-56 shrink-0 flex-wrap lg:flex-col gap-2">
                    <Link
                      to={`/admin/scraper/new-series?draft=${encodeURIComponent(operation.id)}`}
                      className="flex-1 lg:flex-none px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm text-center flex items-center justify-center gap-2"
                    >
                      Open operation <ExternalLink size={14} />
                    </Link>

                    {discoveryFailed && (
                      <button
                        type="button"
                        onClick={() => void retryDiscovery(operation)}
                        disabled={isBusy}
                        className="flex-1 lg:flex-none px-3 py-2 rounded-lg border border-amber-800/60 bg-amber-950/20 hover:bg-amber-950/40 text-amber-200 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                      >
                        <RotateCcw size={14} /> Retry discovery
                      </button>
                    )}

                    {!operation.acknowledged_at && operation.workflow_status !== 'published' && (
                      <button
                        type="button"
                        onClick={() => void cancelOperation(operation)}
                        disabled={isBusy}
                        className="flex-1 lg:flex-none px-3 py-2 rounded-lg border border-red-800/60 bg-red-950/20 hover:bg-red-950/40 text-red-200 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                      >
                        <Trash2 size={14} /> {operation.operation_group === 'running' ? 'Cancel task' : 'Remove operation'}
                      </button>
                    )}

                    {canAcknowledge && !operation.acknowledged_at && (
                      <button
                        type="button"
                        onClick={() => void acknowledge(operation)}
                        disabled={isBusy}
                        className="flex-1 lg:flex-none px-3 py-2 rounded-lg bg-green-700/80 hover:bg-green-700 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                      >
                        <CheckCircle2 size={14} /> Acknowledge
                      </button>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-ink-800 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-ink-600">
                  <span>ID {operation.id}</span>
                  <span>Created {formatDate(operation.created_at)}</span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3 min-w-0">
      <div className="flex items-center gap-2 text-ink-500 text-xs">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="font-display text-xl font-semibold mt-1">{value}</div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-ink-950/70 border border-ink-800 p-2.5">
      <div className="text-ink-600">{label}</div>
      <div className="text-ink-300 mt-0.5 break-words">{value}</div>
    </div>
  );
}
