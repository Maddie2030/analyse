import { acknowledge, checkpoint, createRecord, prepare, scopeKey, type CanonicalReading, type ReadingRecord, type Target } from './model.ts';
export type ReadingState = { epoch: number; records: Record<string, ReadingRecord>; confirmed: Record<string, CanonicalReading>; leases: Record<string, { owner: string; until: number }> };
export const emptyState = (): ReadingState => ({ epoch: 0, records: {}, confirmed: {}, leases: {} });
export interface ReadingStore { transact(scope: string, change: (state: ReadingState) => ReadingState): Promise<ReadingState> }
type Options = { store: ReadingStore; send: (record: ReadingRecord) => Promise<CanonicalReading>; origin: string; account: string | null; uuid: () => string; now: () => number; notify: (confirmed: boolean) => void };
// Each explicit open owns a distinct local record. Tabs never coalesce distinct
// open/completion intentions; the transactional lease only coordinates transport.
export class ReadingRepository {
  readonly scope: string;
  private options: Options;
  private state = emptyState();
  private pending = new Map<string, ReadingRecord>();
  private active = true;
  private suspended = false;
  private authGeneration = 0;
  private loaded = false;
  private initializing = new Set<string>();
  private owner: string;
  private createdClock = 0;
  private inFlight = new Set<string>();
  private retries = new Map<string, { attempts: number; after: number }>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private listeners = new Set<() => void>();
  storageError = '';
  constructor(options: Options) { this.options = options; this.scope = scopeKey(options.origin, options.account); this.owner = options.uuid(); }
  isActive() { return this.active; }
  account() { return this.options.account; }
  suspend() { this.suspended = true; this.authGeneration++; this.emit(); }
  resume() { this.suspended = false; }
  private canSend() { return this.active && !this.suspended; }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private emit(confirmed = false) { this.listeners.forEach(fn => fn()); this.options.notify(confirmed); }
  records() { return Object.values(this.state.records); }
  confirmed(seriesId: string) { return this.state.confirmed[seriesId]; }
  hasVolatile() { return this.pending.size > 0; }
  hasPending() { return this.records().some(r => r.dirty || r.command); }
  private async transaction(change: (state: ReadingState) => ReadingState, includePending = true) {
    if (!this.active) return;
    const captured = includePending ? [...this.pending.values()] : [];
    const epoch = this.loaded ? this.state.epoch : null;
    const next = await this.options.store.transact(this.scope, state => {
      if (!this.active || (epoch !== null && epoch !== state.epoch)) return state;
      for (const local of captured) {
        const persisted = state.records[local.id];
        if (!persisted && local.command?.kind === 'open' && !local.command.sent) {
          // Immediate capture can precede the initial disk read. Attach the
          // new visit behind already-durable work inside this same transaction.
          const prior = Object.values(state.records).filter(r => r.target.series_id === local.target.series_id)
            .sort((a, b) => b.created - a.created || b.id.localeCompare(a.id));
          local.created = Math.max(local.created, (prior[0]?.created || 0) + 1);
          local.touched = Math.max(local.touched, local.created);
          const dependency = prior.find(r => r.command || r.dirty);
          if (dependency) local.command = { ...local.command, depends_on: dependency.id };
          else if (local.command.depends_on && state.confirmed[local.target.series_id]) {
            local.command = { ...local.command, body: { ...local.command.body,
              expected_revision: state.confirmed[local.target.series_id].revision } };
          }
        }
        state.records[local.id] = persisted ? { ...persisted, position: local.position, completed_page: Math.max(local.completed_page, persisted.completed_page), dirty: local.dirty || persisted.dirty, version: local.version, touched: local.touched } : local;
      }
      const now = this.options.now();
      const dependencies = new Set(Object.values(state.records).flatMap(record => record.command?.kind === 'open' && record.command.depends_on ? [record.command.depends_on] : []));
      for (const [id, record] of Object.entries(state.records)) {
        if (!record.dirty && !record.command && !dependencies.has(id) && now - record.touched > 7 * 86400_000) delete state.records[id];
      }
      for (const [id, value] of Object.entries(state.confirmed)) {
        if (value.updated_at && now - Date.parse(value.updated_at) > 7 * 86400_000) delete state.confirmed[id];
      }
      const changed = change(state);
      const tooMany = Object.values(changed.records).filter(r => r.dirty || r.command).length > 500;
      if (tooMany || new TextEncoder().encode(JSON.stringify(changed)).length > 5 * 1024 * 1024) throw new Error('Reading storage limit reached');
      return changed;
    });
    if (!this.active) return;
    if (epoch !== null && epoch !== next.epoch) { this.dispose(); this.state = emptyState(); this.emit(); return; }
    this.loaded = true;
    for (const saved of captured) if (this.pending.get(saved.id)?.version === saved.version) this.pending.delete(saved.id);
    this.state = next;
    this.createdClock = Math.max(this.createdClock, ...Object.values(next.records).map(record => record.created), 0);
    // Edits made while IDB awaited must remain visible and dirty in memory.
    for (const local of this.pending.values()) {
      const saved = this.state.records[local.id];
      this.state.records[local.id] = saved ? { ...saved, position: local.position, completed_page: Math.max(saved.completed_page, local.completed_page), version: local.version, dirty: true } : local;
    }
    if (includePending && !this.pending.size) this.storageError = '';
    this.emit();
  }
  async load() { try { await this.transaction(s => s); } catch { this.storageFailure(); } }
  private storageFailure() { this.storageError = 'Local saving unavailable. Keep this tab open; unsynced reading is only in memory.'; this.emit(); }
  async persist() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    try { await this.transaction(s => s); return !this.storageError; } catch { this.storageFailure(); return false; }
  }
  async open(target: Target, revision: number) {
    const id = this.beginOpen(target, revision);
    await this.persist();
    return id;
  }
  beginOpen(target: Target, revision: number | null) {
    if (!this.active) return '';
    // Each reader visit is an explicit open and keeps its own command. Older
    // pending opens and completions remain ordered ahead of it for this series.
    const created = Math.max(this.options.now(), this.createdClock + 1);
    this.createdClock = created;
    const record = createRecord(target, revision ?? 0, this.options.uuid(), created);
    const dependency = this.records()
      .filter(candidate => candidate.target.series_id === target.series_id && (candidate.command || candidate.dirty))
      .sort((a, b) => b.created - a.created || b.id.localeCompare(a.id))[0];
    if (record.command?.kind === 'open') {
      if (dependency) record.command.depends_on = dependency.id;
      if (revision === null) record.command.awaiting_revision = true;
    }
    this.state.records[record.id] = record;
    this.pending.set(record.id, record);
    this.emit();
    if (!this.timer) this.timer = setTimeout(() => { void this.persist(); }, 1000);
    return record.id;
  }
  holdOpen(id: string) { this.initializing.add(id); }
  async recoverOpens(read?: (target: Target) => Promise<CanonicalReading>) {
    await Promise.all(this.records().filter(r => r.command?.kind === 'open' && r.command.awaiting_revision && !this.initializing.has(r.id)).map(async record => {
      this.initializing.add(record.id);
      let revision = this.confirmed(record.target.series_id)?.revision || 0;
      try { if (read) revision = (await read(record.target)).revision; } catch { /* Last observed revision is retained offline. */ }
      await this.resolveOpen(record.id, revision);
    }));
  }
  async resolveOpen(id: string, revision: number) {
    // Resolve only the initial unknown revision. A dependency's ACK is the
    // ordering authority when earlier offline work exists; sent bodies freeze.
    const resolve = (record: ReadingRecord | undefined) => {
      const command = record?.command;
      if (record && command?.kind === 'open' && !command.sent && command.awaiting_revision) {
        record.command = { ...command, awaiting_revision: false, body: { ...command.body,
          expected_revision: command.depends_on ? command.body.expected_revision : revision } };
      }
    };
    this.initializing.delete(id);
    resolve(this.state.records[id]);
    resolve(this.pending.get(id));
    await this.transaction(state => { resolve(state.records[id]); return state; }).catch(() => this.storageFailure());
  }
  checkpoint(id: string, page: number, scroll: number, completedPage: number) {
    if (!this.active) return;
    const old = this.state.records[id];
    if (!old) return;
    const next = checkpoint(old, page, scroll, completedPage, this.options.uuid());
    if (next === old) return;
    next.touched = this.options.now();
    this.state.records[id] = next;
    this.pending.set(id, next);
    this.emit();
    if (!this.timer) this.timer = setTimeout(() => { void this.persist(); }, 1000);
  }
  async flush(foreground = false) {
    if (!this.active) return;
    await this.persist();
    if (!this.canSend() || this.options.account === null) return;
    const series = [...new Set(this.records().filter(r => (r.command || r.dirty) && !r.paused).map(r => r.target.series_id))];
    await Promise.all(series.map(id => this.flushSeries(id, foreground)));
  }
  private async flushSeries(seriesId: string, foreground: boolean) {
    if (this.inFlight.has(seriesId) || !this.canSend()) return;
    const authGeneration = this.authGeneration;
    const retry = this.retries.get(seriesId);
    if (!foreground && retry && retry.after > this.options.now()) return;
    this.inFlight.add(seriesId);
    let sending: ReadingRecord | undefined;
    try {
      // Payload creation and lease acquisition are one durable transaction.
      await this.transaction(state => {
        const lease = state.leases[seriesId];
        if (lease && lease.owner !== this.owner && lease.until > this.options.now()) return state;
        const record = Object.values(state.records).filter(r => r.target.series_id === seriesId && (r.command || r.dirty)).sort((a, b) => a.created - b.created || a.id.localeCompare(b.id))[0];
        if (!record || record.paused || (record.command?.kind === 'open' && record.command.awaiting_revision)) return state;
        const prepared = prepare(record, this.options.uuid());
        if (!prepared.command) return state;
        if (!prepared.command.sent) prepared.command = { ...prepared.command, sent: true };
        state.records[record.id] = prepared;
        state.leases[seriesId] = { owner: this.owner, until: this.options.now() + 75_000 };
        sending = structuredClone(prepared);
        return state;
      }, false);
      if (!sending || !this.canSend() || authGeneration !== this.authGeneration) return;
      const response = await this.options.send(sending);
      if (!this.canSend() || authGeneration !== this.authGeneration) return;
      let accepted = false;
      await this.transaction(state => {
        if (!this.canSend() || authGeneration !== this.authGeneration) return state;
        const current = state.records[sending!.id];
        if (!current || current.command?.body.command_id !== response.command_id) return state;
        const acknowledged = acknowledge(current, response);
        state.records[current.id] = acknowledged;
        accepted = Boolean(response.accepted && !acknowledged.command);
        if (accepted) {
          for (const candidate of Object.values(state.records)) {
            if (candidate.command?.kind === 'open' && !candidate.command.sent && candidate.command.depends_on === current.id) {
              candidate.command = { ...candidate.command, body: { ...candidate.command.body, expected_revision: response.revision } };
            }
          }
        }
        if (!response.accepted || accepted) {
          const prior = state.confirmed[seriesId];
          if (!prior || prior.revision <= response.revision) state.confirmed[seriesId] = response;
        }
        return state;
      });
      this.retries.delete(seriesId);
      this.emit(accepted);
    } catch (cause) {
      const status = Number((cause as { status?: number }).status);
      if ([400, 401, 403, 404, 422].includes(status) && sending && this.active) {
        this.retries.delete(seriesId);
        await this.transaction(state => {
          const current = state.records[sending!.id];
          if (current) current.paused = status === 401 || status === 403 ? 'authentication_required' : `request_${status}`;
          return state;
        }).catch(() => this.storageFailure());
      } else {
        const attempts = (retry?.attempts || 0) + 1;
        this.retries.set(seriesId, { attempts, after: this.options.now() + Math.min(60_000, 1000 * 2 ** Math.min(attempts, 6)) * (.5 + Math.random() * .5) });
      }
    } finally {
      if (this.active) await this.transaction(state => { if (state.leases[seriesId]?.owner === this.owner) delete state.leases[seriesId]; return state; }, false).catch(() => this.storageFailure());
      this.inFlight.delete(seriesId);
    }
  }
  async reauthenticate() { await this.transaction(state => { Object.values(state.records).forEach(r => { if (r.paused === 'authentication_required') r.paused = null; }); return state; }).catch(() => this.storageFailure()); }
  // Explicit user reconciliation chooses server state by discarding this local
  // intent; a fresh open is a separate user action after the server read.
  async discard(id: string) { this.pending.delete(id); await this.transaction(state => { delete state.records[id]; return state; }); this.emit(true); }
  async dispose() {
    this.active = false;
    if (this.timer) clearTimeout(this.timer);
    const pending = [...this.pending.values()];
    const epoch = this.state.epoch;
    if (!pending.length) return;
    try {
      await this.options.store.transact(this.scope, state => {
        if (state.epoch !== epoch) return state;
        for (const record of pending) {
          const saved = state.records[record.id];
          state.records[record.id] = saved ? { ...saved, position: record.position, completed_page: Math.max(saved.completed_page, record.completed_page), dirty: true, version: record.version, touched: record.touched } : record;
        }
        if (Object.values(state.records).filter(r => r.dirty || r.command).length > 500 || new TextEncoder().encode(JSON.stringify(state)).length > 5 * 1024 * 1024) throw new Error('Reading storage limit reached');
        return state;
      });
    } catch { this.storageFailure(); }
  }
  retryDue() {
    for (const [series, retry] of this.retries) if (retry.after <= this.options.now()) void this.flushSeries(series, false);
  }
  async releaseCleared() {
    // Another tab performed an explicitly authorized clear; never write back.
    this.active = false;
    this.authGeneration++;
    if (this.timer) clearTimeout(this.timer);
    this.pending.clear();
    this.state = emptyState();
    this.emit();
  }
  async clear() {
    await this.dispose();
    this.pending.clear();
    this.state = emptyState();
    await this.options.store.transact(this.scope, state => ({ ...emptyState(), epoch: state.epoch + 1 }));
    this.emit(true);
  }
}
