import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Database,
  Download,
  HardDrive,
  Loader2,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { api, type BackupManifestItem, type DatabaseOperationItem, type DatabaseProtectionStatus } from '../api/client';

function bytes(value?: number) {
  if (!value || value <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let n = value;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function when(value?: string | null) {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleString();
}

function statusClass(status: string) {
  if (status === 'verified' || status === 'completed') return 'text-emerald-300 border-emerald-700/50 bg-emerald-900/20';
  if (status === 'failed') return 'text-red-300 border-red-700/50 bg-red-900/20';
  if (status === 'cancelled') return 'text-ink-400 border-ink-700 bg-ink-900';
  return 'text-amber-300 border-amber-700/50 bg-amber-900/20';
}

function kindLabel(item: BackupManifestItem) {
  return item.kind === 'physical_snapshot' ? 'Physical snapshot' : 'Logical backup';
}

function DatabaseReadinessSummary({ data, canRestoreDrill }: { data: DatabaseProtectionStatus | null; canRestoreDrill: boolean }) {
  const storage = data?.storage;
  const runtime = data?.runtime;
  return (
    <>
<div className="grid md:grid-cols-2 gap-4 mb-4">
  <div className="rounded-xl border border-ink-800 bg-ink-900 p-4">
    <div className="flex items-center gap-2 text-sm text-ink-400 mb-2"><Database size={16} /> Local recovery storage</div>
    <div className={`font-semibold ${data ? (storage?.local_storage_ready ? 'text-emerald-300' : 'text-red-300') : 'text-ink-300'}`}>{data ? (storage?.local_storage_ready ? 'Ready' : 'Unavailable') : 'Unknown'}</div>
    <div className="text-sm text-ink-400 mt-2">{data ? `${storage?.backup_count ?? 0} recovery points indexed` : 'Recovery point count unknown'}</div>
    <p className="text-xs text-ink-500 mt-2">Directory and filename details remain backend-only.</p>
  </div>

  <div className="rounded-xl border border-ink-800 bg-ink-900 p-4">
    <div className="flex items-center gap-2 text-sm text-ink-400 mb-2"><ShieldCheck size={16} /> Recovery engine</div>
    <div className={`font-semibold ${data ? (runtime?.available ? (runtime.status === 'ready' ? 'text-emerald-300' : 'text-amber-300') : 'text-red-300') : 'text-ink-300'}`}>{data ? (runtime?.available ? (runtime.status === 'ready' ? 'Ready' : 'Degraded') : 'Offline') : 'Unknown'}</div>
    <div className="text-xs text-ink-500 mt-2">Last heartbeat: {when(runtime?.last_heartbeat_at)}</div>
    <p className="text-xs text-ink-500 mt-2">{runtime?.message || 'Waiting for operation-engine readiness.'}</p>
  </div>

</div>

{data ? (
  <div className={`mb-6 rounded-xl border p-4 ${storage?.healthy ? 'border-emerald-700/40 bg-emerald-900/10' : 'border-amber-700/50 bg-amber-900/15'}`}>
    <div className={`font-semibold flex items-center gap-2 ${storage?.healthy ? 'text-emerald-300' : 'text-amber-200'}`}>
      {storage?.healthy ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
      {storage?.healthy ? 'Database recovery storage ready' : 'Database recovery storage requires attention'}
    </div>
    <p className="mt-2 text-sm text-ink-300">{storage?.message || 'Checking storage verification…'}</p>
    {!storage?.healthy && storage?.operator_action && <p className="mt-2 text-xs text-ink-500">{storage.operator_action} Detailed paths and diagnostics are available only in backend tooling/logs.</p>}
    {!storage?.healthy && canRestoreDrill && <p className="mt-2 text-xs text-emerald-300">Existing recovery points remain available for checksum-verified restore drills while protected-write operations stay locked.</p>}
  </div>
) : (
  <div className="mb-6 rounded-xl border border-ink-800 bg-ink-900 p-4 text-sm text-ink-400">
    Database recovery status is unavailable. Re-check to load storage verification and recovery-engine readiness.
  </div>
)}
    </>
  );
}

function RecoveryCatalog({
  data, backups, loading, active, action, canRestoreDrill, canRestore, backupCursorStack,
  showPreviousBackupPage, showNextBackupPage, run, onRestore,
}: {
  data: DatabaseProtectionStatus | null;
  backups: BackupManifestItem[];
  loading: boolean;
  active?: DatabaseOperationItem;
  action: string;
  canRestoreDrill: boolean;
  canRestore: boolean;
  backupCursorStack: Array<string | null>;
  showPreviousBackupPage: () => void;
  showNextBackupPage: () => void;
  run: (label: string, fn: () => Promise<unknown>) => Promise<void>;
  onRestore: (item: BackupManifestItem) => void;
}) {
  return (
<section className="rounded-xl border border-ink-800 bg-ink-900 overflow-hidden mb-6">
  <div className="p-4 border-b border-ink-800 flex items-center justify-between gap-3">
    <div><h2 className="font-display font-bold">Verified recovery points</h2><p className="text-xs text-ink-500 mt-1">Internal storage paths and original object names are intentionally hidden. All actions use protected opaque backup identifiers.</p></div>
    <span className="text-xs text-ink-500">{data ? `${backups.length} of ${data.backup_page.total} indexed` : 'Recovery catalog unavailable'}</span>
  </div>
  <div className="overflow-x-auto">
    <table className="w-full text-sm min-w-[820px]">
      <thead className="text-left text-ink-500 border-b border-ink-800"><tr><th className="p-3">Recovery point</th><th className="p-3">Taken</th><th className="p-3">Size</th><th className="p-3">Release</th><th className="p-3 text-right">Actions</th></tr></thead>
      <tbody>
        {!data && !loading && <tr><td colSpan={5} className="p-5 text-center text-ink-500">Recovery catalog unavailable. Re-check to load verified recovery points.</td></tr>}
        {data && backups.length === 0 && <tr><td colSpan={5} className="p-5 text-center text-ink-500">No verified recovery points are indexed.</td></tr>}
        {backups.map((item) => <tr key={item.id} className="border-b border-ink-800/60 last:border-0 align-top">
          <td className="p-3"><span className="inline-flex items-center gap-1.5"><CheckCircle2 size={14} className="text-emerald-400" />{kindLabel(item)}</span><div className="text-xs text-ink-600 mt-1">{item.type}</div></td>
          <td className="p-3 whitespace-nowrap">{when(item.timestamp_local || item.timestamp_utc)}</td>
          <td className="p-3 whitespace-nowrap">{bytes(item.size_bytes)}</td>
          <td className="p-3 text-xs text-ink-400">{item.mreader_version || '—'}</td>
          <td className="p-3"><div className="flex justify-end flex-wrap gap-2">
            <a href={`/api/admin/database/backups/${encodeURIComponent(item.id)}/download`} title="Download this checksum-verified recovery artifact through the private recovery bridge." className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-ink-800 hover:bg-ink-700"><Download size={14} /> Download</a>
            <button title={canRestoreDrill ? 'Restore into an isolated validation target without modifying production.' : 'Restore drill operation engine is not currently ready.'} disabled={Boolean(active) || Boolean(action) || !canRestoreDrill} onClick={() => void run('Restore drill', () => api.createDatabaseRestoreDrill(item.id))} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-ink-800 hover:bg-ink-700 disabled:opacity-50"><PlayCircle size={14} /> Drill</button>
            <button title={canRestore ? 'Stage, validate, create a safety recovery point, then perform guarded cutover.' : 'Production restore stays locked until protected pre-restore backup capability is ready.'} disabled={Boolean(active) || Boolean(action) || !canRestore} onClick={() => onRestore(item)} className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-red-900/40 hover:bg-red-900/60 text-red-300 disabled:opacity-50"><RotateCcw size={14} /> Restore</button>
          </div></td>
        </tr>)}
      </tbody>
    </table>
  </div>
  <div className="border-t border-ink-800 px-4 py-3 flex items-center justify-between gap-3">
    <button onClick={showPreviousBackupPage} disabled={backupCursorStack.length === 0 || loading} className="px-3 py-1.5 rounded bg-ink-800 hover:bg-ink-700 disabled:opacity-40 text-xs">Previous page</button>
    <span className="text-xs text-ink-500">{data ? `${data.backup_page.total} verified recovery points` : 'Recovery point count unknown'}</span>
    <button onClick={showNextBackupPage} disabled={!data?.backup_page.next_cursor || loading} className="px-3 py-1.5 rounded bg-ink-800 hover:bg-ink-700 disabled:opacity-40 text-xs">Next page</button>
  </div>
</section>
  );
}

function OperationHistory({ data, loading, run }: {
  data: DatabaseProtectionStatus | null;
  loading: boolean;
  run: (label: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  return (
<section className="rounded-xl border border-ink-800 bg-ink-900 overflow-hidden">
  <div className="p-4 border-b border-ink-800"><h2 className="font-display font-bold">Database operation history</h2><p className="text-xs text-ink-500 mt-1">Browser-safe operation status. Detailed internal diagnostics remain in backend logs.</p></div>
  <div className="overflow-x-auto"><table className="w-full text-sm min-w-[760px]"><thead className="text-left text-ink-500 border-b border-ink-800"><tr><th className="p-3">Operation</th><th className="p-3">Status</th><th className="p-3">Phase</th><th className="p-3">Requested</th><th className="p-3">Message</th><th className="p-3"></th></tr></thead><tbody>
    {!data && !loading && <tr><td colSpan={6} className="p-5 text-center text-ink-500">Operation history unavailable. Re-check to load database operations.</td></tr>}
    {data && data.operations.length === 0 && <tr><td colSpan={6} className="p-5 text-center text-ink-500">No database operations recorded.</td></tr>}
    {(data?.operations || []).map((op: DatabaseOperationItem) => <tr key={op.id} className="border-b border-ink-800/60 last:border-0"><td className="p-3">{op.operation_type}</td><td className="p-3"><span className={`inline-flex rounded border px-2 py-1 text-xs ${statusClass(op.status)}`}>{op.status}</span></td><td className="p-3 text-ink-400">{op.phase}</td><td className="p-3 whitespace-nowrap"><div>{when(op.requested_at)}</div><div className="text-xs text-ink-600">{op.requested_by_username || 'system/admin'}</div></td><td className="p-3 text-xs text-ink-400 max-w-sm break-words">{op.message}</td><td className="p-3 text-right">{op.status === 'queued' && <button onClick={() => void run('Cancel', () => api.cancelDatabaseOperation(op.id))} className="inline-flex items-center gap-1 text-xs text-red-300"><XCircle size={14} /> Cancel</button>}</td></tr>)}
  </tbody></table></div>
</section>
  );
}

export default function AdminDatabase() {
  const [data, setData] = useState<DatabaseProtectionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [restoreTarget, setRestoreTarget] = useState<BackupManifestItem | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [backupCursor, setBackupCursor] = useState<string | null>(null);
  const [backupCursorStack, setBackupCursorStack] = useState<Array<string | null>>([]);
  const loadRequestRef = useRef(0);
  const backupCursorRef = useRef<string | null>(backupCursor);
  backupCursorRef.current = backupCursor;

  const load = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    const cursor = backupCursorRef.current;
    setLoading(true);
    setError('');
    try {
      const next = await api.getDatabaseProtection(75, cursor);
      if (requestId !== loadRequestRef.current) return;
      setData(next);
    } catch (err: any) {
      if (requestId !== loadRequestRef.current) return;
      setError(err?.detail || err?.message || 'Failed to load database protection status.');
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [backupCursor, load]);
  useEffect(() => {
    const hasActiveOperation = data?.operations.some((item) => item.status === 'queued' || item.status === 'running');
    const timer = window.setInterval(() => void load(), hasActiveOperation ? 4000 : 15000);
    return () => window.clearInterval(timer);
  }, [data?.operations, load]);

  const backups = useMemo(
    () => [...(data?.backups || [])].sort((a, b) => String(b.timestamp_utc || '').localeCompare(String(a.timestamp_utc || ''))),
    [data],
  );
  const active = data?.operations.find((item) => item.status === 'queued' || item.status === 'running');

  function showNextBackupPage() {
    const nextCursor = data?.backup_page.next_cursor;
    if (!nextCursor) return;
    setBackupCursorStack((stack) => [...stack, backupCursor]);
    setBackupCursor(nextCursor);
  }

  function showPreviousBackupPage() {
    if (backupCursorStack.length === 0) return;
    const previousCursor = backupCursorStack[backupCursorStack.length - 1] ?? null;
    setBackupCursorStack((stack) => stack.slice(0, -1));
    setBackupCursor(previousCursor);
  }

  async function run(label: string, fn: () => Promise<unknown>) {
    if (action) return;
    setAction(label);
    setError('');
    setMessage('');
    try {
      await fn();
      setMessage(`${label} request accepted.`);
      await load();
    } catch (err: any) {
      setError(err?.detail || err?.message || `${label} failed.`);
    } finally {
      setAction('');
    }
  }

  async function requestRestore() {
    if (!restoreTarget) return;
    const restoreControl = data?.runtime.restore_control;
    if (!restoreControl?.installation_fingerprint || !restoreControl.restore_generation) {
      setError('Restore control changed or is unavailable. Refresh and retry.');
      return;
    }
    const expected = `RESTORE ${restoreTarget.id} ON ${restoreControl.installation_fingerprint} GEN ${restoreControl.restore_generation}`;
    if (confirmation !== expected) {
      setError('Restore confirmation did not match the selected backup, installation and generation.');
      return;
    }
    await run('Restore', () => api.createDatabaseRestore(
      restoreTarget.id,
      confirmation,
      restoreControl.installation_fingerprint,
      restoreControl.restore_generation,
    ));
    setRestoreTarget(null);
    setConfirmation('');
  }

  const storage = data?.storage;
  const runtime = data?.runtime;
  const capabilities = runtime?.capabilities;
  const canLogicalBackup = Boolean(runtime?.available && capabilities?.logical_backup);
  const canPhysicalSnapshot = Boolean(runtime?.available && capabilities?.physical_snapshot);
  const canRestoreDrill = Boolean(runtime?.available && capabilities?.restore_drill);
  const canRestore = Boolean(runtime?.available && capabilities?.restore);
  const restoreControl = data?.runtime.restore_control;
  const restoreConfirmation = restoreTarget && restoreControl?.installation_fingerprint && restoreControl.restore_generation
    ? `RESTORE ${restoreTarget.id} ON ${restoreControl.installation_fingerprint} GEN ${restoreControl.restore_generation}`
    : '';

  return (
    <div className="w-full min-w-0 max-w-7xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4 mb-6">
        <div>
          <h1 className="font-display text-2xl sm:text-3xl font-bold flex items-center gap-2"><ShieldCheck size={28} /> Database Protection</h1>
          <p className="text-sm text-ink-400 mt-2 max-w-3xl">PostgreSQL backup, restore-drill and recovery controls. Internal filesystem paths, storage endpoints and device details remain backend-only and are intentionally not exposed to the browser.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => void load()} disabled={loading} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 text-sm"><RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Re-check</button>
          <button title={canLogicalBackup ? 'Create a checksum-verified logical recovery point.' : 'Unavailable until the database protection engine reports protected-write readiness.'} onClick={() => void run('Logical backup', api.createDatabaseBackup)} disabled={Boolean(active) || Boolean(action) || !canLogicalBackup} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-sm font-medium"><Archive size={16} /> Logical backup now</button>
          <button title={canPhysicalSnapshot ? 'Create a physical PostgreSQL snapshot.' : 'Unavailable until protected storage and replication readiness are both verified.'} onClick={() => void run('Physical snapshot', api.createDatabaseSnapshot)} disabled={Boolean(active) || Boolean(action) || !canPhysicalSnapshot} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 disabled:opacity-50 text-sm font-medium"><HardDrive size={16} /> Physical snapshot now</button>
        </div>
      </div>

      {error && <div className="mb-4 rounded-lg border border-red-700/50 bg-red-900/20 px-4 py-3 text-sm text-red-300">{error}</div>}
      {message && <div className="mb-4 rounded-lg border border-emerald-700/40 bg-emerald-900/20 px-4 py-3 text-sm text-emerald-300">{message}</div>}

      <DatabaseReadinessSummary data={data} canRestoreDrill={canRestoreDrill} />

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        <section className="rounded-xl border border-ink-800 bg-ink-900 p-4">
          <h2 className="font-display font-bold mb-3">Backup policy</h2>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-ink-500">Timezone</dt><dd>{data?.policy.timezone || '—'}</dd>
            <dt className="text-ink-500">Automatic window</dt><dd>{data ? `${data.policy.automatic_window_start}–${data.policy.automatic_window_end}` : '—'}</dd>
            <dt className="text-ink-500">Logical retention</dt><dd>{data ? `${data.policy.logical_retention_days} days` : '—'}</dd>
            <dt className="text-ink-500">Snapshot retention</dt><dd>{data ? `${data.policy.snapshot_retention_days} days` : '—'}</dd>
          </dl>
        </section>
        <section className="rounded-xl border border-ink-800 bg-ink-900 p-4">
          <h2 className="font-display font-bold mb-3">Recovery safety</h2>
          <ul className="text-sm text-ink-400 space-y-1.5 list-disc pl-5">
            <li>Restore drills are isolated and never modify the live database.</li>
            <li>Logical backups and physical snapshots are checksum-verified before recovery.</li>
            <li>Physical snapshots are booted and validated in isolation before entering the guarded cutover pipeline.</li>
            <li>A fresh pre-restore safety backup is created before production cutover.</li>
            <li>Production restore requires typed confirmation for the selected opaque backup identifier.</li>
          </ul>
        </section>
      </div>

      <RecoveryCatalog
        data={data}
        backups={backups}
        loading={loading}
        active={active}
        action={action}
        canRestoreDrill={canRestoreDrill}
        canRestore={canRestore}
        backupCursorStack={backupCursorStack}
        showPreviousBackupPage={showPreviousBackupPage}
        showNextBackupPage={showNextBackupPage}
        run={run}
        onRestore={(item) => { setRestoreTarget(item); setConfirmation(''); setError(''); }}
      />

      <OperationHistory data={data} loading={loading} run={run} />

      {restoreTarget && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4" role="dialog" aria-modal="true">
        <div className="w-full max-w-2xl rounded-xl border border-red-800/60 bg-ink-950 p-5 shadow-2xl">
          <h2 className="font-display text-xl font-bold text-red-300 flex items-center gap-2"><AlertTriangle size={20} /> Confirm production database restore</h2>
          <p className="text-sm text-ink-300 mt-3">The selected recovery point is staged and validated first, a fresh safety backup is created, and only then can the database cutover occur.</p>
          <div className="mt-4 rounded-lg bg-ink-900 border border-ink-800 p-3 text-sm"><div>{kindLabel(restoreTarget)}</div><div className="text-xs text-ink-500 mt-1">Taken {when(restoreTarget.timestamp_local || restoreTarget.timestamp_utc)}</div></div>
          <label className="block text-sm text-ink-400 mt-4">Type exactly:</label>
          <div className="font-mono text-xs text-red-300 mt-1 break-all">{restoreConfirmation || 'Restore control unavailable; refresh before continuing.'}</div>
          <input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} className="mt-2 w-full rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-sm outline-none focus:border-red-600" autoComplete="off" />
          <div className="flex justify-end gap-2 mt-5">
            <button onClick={() => { setRestoreTarget(null); setConfirmation(''); }} className="px-4 py-2 rounded-lg bg-ink-800 hover:bg-ink-700">Cancel</button>
            <button disabled={!restoreConfirmation || confirmation !== restoreConfirmation || Boolean(action)} onClick={() => void requestRestore()} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white font-medium">{action === 'Restore' ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />} Restore database</button>
          </div>
        </div>
      </div>}
    </div>
  );
}
