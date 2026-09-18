import { test } from 'node:test';
import assert from 'node:assert/strict';
const model = await import('../../frontend/src/reading/model.ts');
const target = { series_id: 's', chapter_id: 'c', series_slug: 'series', chapter_slug: 'chapter', page_count: 10 };
const canonical = { series_id: 's', chapter_id: 'c', revision: 2, session_generation: 7, command_sequence: 0, last_page: 1, scroll_position: 0, accepted: true, duplicate: false, code: 'accepted', command_id: 'open' };
function opened() {
  assert.equal(typeof model.createRecord, 'function', 'production reading reducer must exist');
  return model.acknowledge(model.createRecord(target, 0, 'open', 1), canonical);
}
test('generation N ACK cannot erase generation N+1 checkpoint', () => {
  let record = model.checkpoint(opened(), 3, .3, 0, 'N');
  record = model.prepare(record, 'commit');
  record = model.checkpoint(record, 5, .5, 0, 'N+1');
  record = model.acknowledge(record, { ...canonical, command_id: 'commit', command_sequence: 1, revision: 3 });
  assert.equal(record.dirty, true);
  assert.equal(record.version, 'N+1');
  assert.equal(record.position.last_page, 5);
  assert.equal(record.command, null);
});
test('timeout retry keeps exact payload and sequence while newer position accumulates', () => {
  const record = model.prepare(model.checkpoint(opened(), 3, .3, 0, 'N'), 'commit');
  const newer = model.prepare(model.checkpoint(record, 5, .5, 0, 'N+1'), 'different');
  assert.deepEqual(newer.command, record.command);
  assert.equal(newer.command.body.command_sequence, 1);
});
test('rejected stale session retains intent and pauses without rebase', () => {
  const record = model.prepare(model.checkpoint(opened(), 3, .3, 0, 'N'), 'commit');
  const rejected = model.acknowledge(record, { ...canonical, command_id: 'commit', accepted: false, code: 'stale_session', revision: 9 });
  assert.deepEqual(rejected.command, record.command);
  assert.equal(rejected.paused, 'stale_session');
  assert.equal(rejected.session_generation, 7);
  assert.deepEqual(model.prepare(rejected, 'rebase'), rejected);
});
test('completion evidence survives returning to an earlier resume page', () => {
  const end = model.checkpoint(opened(), 10, 1, 10, 'end');
  const earlier = model.prepare(model.checkpoint(end, 2, .1, 0, 'back'), 'commit');
  assert.equal(earlier.command.body.last_page, 2);
  assert.equal(earlier.command.body.completed, true);
  assert.equal(earlier.command.body.completed_page, 10);
});
test('pending overlay never changes canonical counts or completion and clean entries disappear', () => {
  const original = { summary: { history: 2, caught_up: 1 }, items: [{ series_id: 's', read_state: 'updates', unread_chapter_count: 4 }] };
  const record = model.checkpoint(opened(), 3, .3, 0, 'N');
  const preview = model.pendingPreview([record], 's');
  assert.equal(preview.last_page, 3);
  assert.deepEqual(original.summary, { history: 2, caught_up: 1 });
  assert.equal('read_state' in preview, false);
  assert.equal('completed' in preview, false);
  assert.equal(model.pendingPreview([opened()], 's'), null);
});
test('account and origin scope are collision-safe and guests cannot share account queues', () => {
  assert.notEqual(model.scopeKey('https://a', 'user'), model.scopeKey('https://b', 'user'));
  assert.notEqual(model.scopeKey('https://a', null), model.scopeKey('https://a', 'guest'));
});
test('open must be accepted before dependent commit and unrelated ACK is inert', () => {
  const record = model.createRecord(target, 0, 'open', 1);
  const dirty = model.checkpoint(record, 3, .3, 0, 'N');
  assert.equal(model.prepare(dirty, 'commit').command.kind, 'open');
  assert.deepEqual(model.acknowledge(dirty, { ...canonical, command_id: 'other' }), dirty);
});
test('completion requires observed end and every relevant page loaded', () => {
  assert.equal(model.completionEvidence(false, [1, 2], new Set([1, 2]), 2), 0);
  assert.equal(model.completionEvidence(true, [1, 2], new Set([1]), 2), 0);
  assert.equal(model.completionEvidence(true, [1, 2], new Set([1, 2]), 2), 2);
  assert.equal(model.completionEvidence(true, [], new Set(), 0), 0);
});
const runtime = await import('../../frontend/src/reading/repository.ts');
const indexedRuntime = await import('../../frontend/src/reading/indexedDB.ts');
class MemoryStore {
  states = new Map();
  tail = Promise.resolve();
  transact(scope, change) {
    const result = this.tail.then(() => {
      const state = structuredClone(this.states.get(scope) || { epoch: 0, records: {}, confirmed: {}, leases: {} });
      const next = change(state);
      this.states.set(scope, structuredClone(next));
      return next;
    });
    this.tail = result.catch(() => {});
    return result;
  }
}
function repository(store, send, account = 'alice') {
  assert.equal(typeof runtime.ReadingRepository, 'function', 'production async repository must exist');
  let id = 0;
  return new runtime.ReadingRepository({ store, send, origin: 'https://a', account, uuid: () => `uuid-${++id}`, now: () => 100, notify: () => {} });
}
test('repository persists exact open before transport and resumes commit after accepted open', async () => {
  const store = new MemoryStore();
  const sent = [];
  const repo = repository(store, async (record) => {
    assert.deepEqual(store.states.get(repo.scope).records[record.id].command, record.command);
    sent.push(record.command);
    return { ...canonical, command_id: record.command.body.command_id };
  });
  await repo.load();
  const id = await repo.open(target, 0);
  repo.checkpoint(id, 4, .4, 0);
  await repo.flush();
  assert.equal(sent[0].kind, 'open');
  await repo.flush();
  assert.equal(sent[1].body.session_generation, 7);
  assert.equal(sent[1].body.last_page, 4);
});
test('reload after timeout retries the exact durable open payload', async () => {
  const store = new MemoryStore();
  let original;
  const first = repository(store, async record => {
    original = structuredClone(record.command.body);
    throw new Error('timeout');
  });
  await first.load();
  await first.open(target, 0);
  await first.flush(true);
  await first.dispose();
  let retried;
  const second = repository(store, async record => {
    retried = structuredClone(record.command.body);
    return { ...canonical, command_id: record.command.body.command_id };
  });
  await second.load();
  await second.flush(true);
  assert.deepEqual(retried, original);
});
test('logout tombstone fences a delayed ACK and clears private pending data', async () => {
  const store = new MemoryStore();
  let resolve;
  let started;
  const waiting = new Promise(r => { started = r; });
  const repo = repository(store, record => { started(); return new Promise(r => { resolve = () => r({ ...canonical, command_id: record.command.body.command_id }); }); });
  await repo.load();
  await repo.open(target, 0);
  const flight = repo.flush();
  await waiting;
  await repo.clear();
  resolve();
  await flight;
  assert.deepEqual(store.states.get(repo.scope).records, {});
  assert.deepEqual(store.states.get(repo.scope).confirmed, {});
});
test('guest and switched account never send previous account intent', async () => {
  const store = new MemoryStore();
  let sends = 0;
  const guest = repository(store, async () => { sends++; return canonical; }, null);
  await guest.load();
  await guest.open(target, 0);
  await guest.flush();
  guest.dispose();
  const bob = repository(store, async () => { sends++; return canonical; }, 'bob');
  await bob.load();
  await bob.flush();
  assert.equal(sends, 0);
  assert.deepEqual(bob.records(), []);
});
test('repository ACK race retains a checkpoint produced during actual transport', async () => {
  const store = new MemoryStore();
  let repo;
  let id;
  let calls = 0;
  repo = repository(store, async record => {
    if (++calls === 2) repo.checkpoint(id, 8, .8, 0);
    return { ...canonical, command_id: record.command.body.command_id, command_sequence: calls - 1 };
  });
  await repo.load(); id = await repo.open(target, 0); await repo.flush();
  repo.checkpoint(id, 3, .3, 0); await repo.flush();
  const pending = repo.records().find(r => r.id === id);
  assert.equal(pending.position.last_page, 8);
  assert.equal(pending.dirty, true);
  assert.equal(pending.command, null);
});
test('account disposal persists coalesced intent before stopping without uploading it', async () => {
  const store = new MemoryStore();
  const repo = repository(store, async () => { throw new Error('must not send'); });
  await repo.load(); const id = await repo.open(target, 0);
  repo.checkpoint(id, 6, .6, 0);
  await repo.dispose();
  assert.equal(store.states.get(repo.scope).records[id].position.last_page, 6);
});
test('storage failure keeps memory intent visible and prevents unpersisted commands from sending', async () => {
  let sends = 0;
  const repo = repository({ transact: async () => { throw new Error('quota'); } }, async () => { sends++; return canonical; });
  await repo.load(); const id = await repo.open(target, 0); repo.checkpoint(id, 7, .7, 0);
  await repo.flush();
  assert.equal(repo.records()[0].position.last_page, 7);
  assert.match(repo.storageError, /unavailable/i);
  assert.equal(sends, 0);
  await repo.dispose();
});
test('open ACK selecting a different canonical chapter pauses instead of adopting its session', () => {
  const record = model.createRecord(target, 0, 'open', 1);
  const ack = model.acknowledge(record, { ...canonical, chapter_id: 'different' });
  assert.equal(ack.paused, 'invalid_response');
  assert.equal(ack.session_generation, 0);
  assert.equal(ack.command.body.command_id, 'open');
});
test('duplicate open ACK adopts the canonical sequence already advanced by another tab', () => {
  const record = model.createRecord(target, 2, 'open', 1);
  const ack = model.acknowledge(record, { ...canonical, duplicate: true, code: 'duplicate', command_sequence: 4 });
  assert.equal(ack.session_generation, 7);
  assert.equal(ack.sequence, 4);
  const prepared = model.prepare(model.checkpoint(ack, 6, .6, 0, 'later'), 'commit-after-duplicate');
  assert.equal(prepared.command.body.command_sequence, 5);
});
test('each explicit open retains a distinct ordered intent', async () => {
  const store = new MemoryStore();
  const repo = repository(store, async () => canonical);
  await repo.load();
  const first = await repo.open(target, 0);
  const second = await repo.open(target, 0);
  assert.notEqual(first, second);
  assert.equal(repo.records().filter(record => record.command?.kind === 'open').length, 2);
});
test('ordered offline chapter opens advance an unsent dependent revision exactly once', async () => {
  const store = new MemoryStore();
  let revision = 0;
  let generation = 0;
  const sent = [];
  const repo = repository(store, async record => {
    sent.push(structuredClone(record.command));
    if (record.command.kind === 'open') {
      assert.equal(record.command.body.expected_revision, revision);
      generation++;
      revision++;
      return { ...canonical, series_id: record.target.series_id, chapter_id: record.target.chapter_id,
        revision, session_generation: generation, command_sequence: 0, command_id: record.command.body.command_id };
    }
    assert.equal(record.command.body.session_generation, generation);
    revision++;
    return { ...canonical, series_id: record.target.series_id, chapter_id: record.target.chapter_id,
      revision, session_generation: generation, command_sequence: record.command.body.command_sequence, command_id: record.command.body.command_id };
  });
  await repo.load();
  const first = await repo.open(target, 0);
  repo.checkpoint(first, 3, .3, 0);
  const secondTarget = { ...target, chapter_id: 'c2', chapter_slug: 'chapter-2' };
  const second = await repo.open(secondTarget, 0);
  repo.checkpoint(second, 4, .4, 0);
  for (let index = 0; index < 4; index++) await repo.flush(true);
  assert.deepEqual(sent.map(command => command.kind), ['open', 'commit', 'open', 'commit']);
  assert.deepEqual(sent.filter(command => command.kind === 'open').map(command => command.body.expected_revision), [0, 2]);
  assert.equal(repo.hasPending(), false);
});
test('shared transactional store preserves a second tab checkpoint across first tab ACK', async () => {
  const store = new MemoryStore();
  let release;
  let transportStarted;
  const started = new Promise(resolve => { transportStarted = resolve; });
  const first = repository(store, record => {
    if (record.command.kind === 'commit') {
      transportStarted();
      return new Promise(resolve => { release = () => resolve({ ...canonical, revision: 3, command_id: record.command.body.command_id, command_sequence: 1 }); });
    }
    return Promise.resolve({ ...canonical, command_id: record.command.body.command_id });
  });
  const second = repository(store, async () => { throw new Error('second tab must not transport'); });
  await first.load();
  const id = await first.open(target, 0);
  await first.flush();
  first.checkpoint(id, 3, .3, 0);
  const flight = first.flush();
  await transportStarted;
  await second.load();
  second.checkpoint(id, 9, .9, 0);
  await second.persist();
  release();
  await flight;
  await second.load();
  const retained = second.records().find(record => record.id === id);
  assert.equal(retained.position.last_page, 9);
  assert.equal(retained.dirty, true);
  assert.equal(retained.command, null);
});
test('production IndexedDB store serializes cross-instance read-modify-write transactions', async () => {
  assert.equal(typeof indexedRuntime.IndexedReadingStore, 'function', 'production IndexedDB store must exist');
  const original = globalThis.indexedDB;
  const values = new Map();
  let transactionTail = Promise.resolve();
  const database = {
    onversionchange: null,
    close() {},
    createObjectStore() {},
    transaction() {
      let readRequest;
      let staged;
      let aborted = false;
      const transaction = {
        error: null,
        oncomplete: null,
        onerror: null,
        onabort: null,
        abort() { aborted = true; },
        objectStore() {
          return {
            get(key) { readRequest = { result: undefined, error: null, onsuccess: null }; readRequest.key = key; return readRequest; },
            put(value, key) { staged = [key, structuredClone(value)]; },
          };
        },
      };
      const run = transactionTail.then(() => new Promise(resolve => queueMicrotask(() => {
        readRequest.result = values.has(readRequest.key) ? structuredClone(values.get(readRequest.key)) : undefined;
        readRequest.onsuccess();
        queueMicrotask(() => {
          if (aborted) transaction.onabort?.();
          else {
            if (staged) values.set(staged[0], staged[1]);
            transaction.oncomplete?.();
          }
          resolve();
        });
      })));
      transactionTail = run.catch(() => {});
      return transaction;
    },
  };
  globalThis.indexedDB = {
    open() {
      const request = { result: database, error: null, onupgradeneeded: null, onerror: null, onblocked: null, onsuccess: null };
      queueMicrotask(() => { request.onupgradeneeded?.(); request.onsuccess?.(); });
      return request;
    },
  };
  try {
    const notifications = [];
    const first = new indexedRuntime.IndexedReadingStore((scope, confirmed) => notifications.push([scope, confirmed]));
    const second = new indexedRuntime.IndexedReadingStore((scope, confirmed) => notifications.push([scope, confirmed]));
    await Promise.all([
      first.transact('scope', state => { state.leases.first = { owner: 'one', until: 1 }; return state; }),
      second.transact('scope', state => { state.leases.second = { owner: 'two', until: 2 }; return state; }),
    ]);
    const state = await first.transact('scope', current => current);
    assert.deepEqual(Object.keys(state.leases).sort(), ['first', 'second']);
    assert.deepEqual(notifications, [['scope', false], ['scope', false]]);
  } finally {
    if (original === undefined) delete globalThis.indexedDB;
    else globalThis.indexedDB = original;
  }
});
test('pending limit retains overflow in memory while existing durable intentions can sync', async () => {
  const store = new MemoryStore();
  let sends = 0;
  const repo = repository(store, async record => { sends++; return { ...canonical, command_id: record.command.body.command_id, series_id: record.target.series_id, chapter_id: record.target.chapter_id }; });
  const state = { epoch: 0, records: {}, confirmed: {}, leases: {} };
  for (let i = 0; i < 500; i++) {
    const record = model.createRecord({ ...target, series_id: `s${i}`, chapter_id: `c${i}` }, 0, `open-${i}`, i);
    if (i > 0) record.paused = 'revision_conflict';
    state.records[record.id] = record;
  }
  store.states.set(repo.scope, state);
  await repo.load();
  const overflow = await repo.open({ ...target, series_id: 'overflow', chapter_id: 'overflow' }, 0);
  assert.equal(repo.records().length, 501);
  assert.match(repo.storageError, /unavailable/i);
  await repo.flush();
  assert.ok(sends >= 1, 'existing durable record must still be able to drain');
  assert.ok(repo.records().find(r => r.id === overflow), 'overflow intent must not be discarded');
  assert.ok(Object.values(store.states.get(repo.scope).records).filter(r => r.command || r.dirty).length <= 500);
});

const accountRuntime = await import('../../frontend/src/reading/accounts.ts').catch(() => ({}));
const transportRuntime = await import('../../frontend/src/reading/transport.ts').catch(() => ({}));
const visitRuntime = await import('../../frontend/src/reading/visit.ts').catch(() => ({}));
test('two tab controllers fence stale uploads against a genuinely shared cookie identity', async () => {
  assert.equal(typeof accountRuntime.ReadingAccounts, 'function');
  assert.equal(typeof transportRuntime.readingTransport, 'function');
  const store = new MemoryStore();
  let cookieAccount = 'alice';
  const persisted = [];
  const requests = [];
  const transport = transportRuntime.readingTransport(async (url, options) => {
    const identity = new Headers(options.headers).get('X-MReader-Account-ID');
    requests.push({ url, identity });
    if (identity !== cookieAccount) throw { status: 403, code: 'account_mismatch' };
    if (options.method === 'POST') persisted.push({ account: cookieAccount, body: JSON.parse(options.body) });
    return { ...canonical, command_id: options.body ? JSON.parse(options.body).command_id : undefined };
  });
  const notices = [];
  const controller = () => new accountRuntime.ReadingAccounts({
    create: account => repository(store, record => transport.send(account, record), account),
    notify: () => {}, publish: message => notices.push(message), invalidateAuth: () => {},
  });
  const first = controller(); const second = controller();
  await first.select('alice'); await second.select('alice');
  await first.current().open(target, 0);
  cookieAccount = 'bob';
  await second.select('bob');
  // Deliberately delay broadcast delivery until AFTER a stale tab transports.
  await first.current().flush(true);
  assert.deepEqual(persisted, []);
  assert.equal(first.current().records()[0].paused, 'authentication_required');
  await assert.rejects(transport.getProgress('alice', 'series', 'chapter'), { status: 403 });
  const staleCommit = model.prepare(model.checkpoint(opened(), 4, .4, 0, 'checkpoint'), 'commit');
  await assert.rejects(transport.send('alice', staleCommit), { status: 403 });
  assert.deepEqual(persisted, [], 'stale opens and commits cannot create Bob history');
  assert.ok(requests.every(request => request.identity === 'alice'));
  first.receive(notices.at(-1));
  assert.equal(first.current(), null, 'unverified broadcast must hide private scope');
  assert.match(first.warning(), /paused/i);
  await first.select('bob');
  assert.deepEqual(first.current().records(), []);
  cookieAccount = 'alice';
  await first.select('alice'); await first.current().flush(true);
  assert.deepEqual(persisted.map(value => value.account), ['alice']);
});
test('automatic auth loss retains volatile private intent and warning until same account returns', async () => {
  assert.equal(typeof accountRuntime.ReadingAccounts, 'function');
  const store = new MemoryStore(); let fail = true; let sends = 0;
  const accounts = new accountRuntime.ReadingAccounts({
    create: account => repository({ transact: (...args) => fail ? Promise.reject(new Error('quota')) : store.transact(...args) }, async record => {
      sends++; return { ...canonical, command_id: record.command.body.command_id };
    }, account), notify: () => {}, publish: () => {}, invalidateAuth: () => {},
  });
  await accounts.select('alice'); const original = accounts.current();
  const id = await original.open(target, 0); original.checkpoint(id, 9, .9, 10);
  await accounts.select(null); await original.flush(true);
  assert.equal(sends, 0); assert.match(accounts.warning(), /memory/i);
  assert.deepEqual(accounts.current().records(), [], 'guest UI cannot inspect private chapters');
  await accounts.select('bob'); assert.deepEqual(accounts.current().records(), []);
  await accounts.select('alice'); assert.equal(accounts.current(), original);
  assert.equal(original.records()[0].position.last_page, 9); assert.equal(original.records()[0].completed_page, 10);
  fail = false; await original.flush(true); assert.equal(sends, 1);
  await accounts.clearPrivate(); assert.equal(original.records().length, 0);
  assert.ok(store.states.get(original.scope).epoch > 0);
});
test('reader captures position, completion and exit before delayed GET without late navigation reset', async () => {
  assert.equal(typeof visitRuntime.ReadingVisit, 'function');
  const store = new MemoryStore(); const sent = []; let resolveRead;
  const repo = repository(store, async record => { sent.push(structuredClone(record.command)); return { ...canonical, command_id: record.command.body.command_id }; });
  await repo.load();
  const restores = [];
  const visit = new visitRuntime.ReadingVisit({ repository: repo, target,
    read: () => new Promise(resolve => { resolveRead = resolve; }), restore: position => restores.push(position) });
  visit.capture(8, .82, 10, true);
  assert.equal(repo.records()[0].position.last_page, 8);
  assert.equal(repo.records()[0].completed_page, 10);
  await repo.flush(true); assert.equal(sent.length, 0, 'unknown revision cannot transport');
  visit.close();
  resolveRead({ ...canonical, revision: 12, last_page: 3, scroll_position: .23 });
  await visit.ready;
  assert.deepEqual(restores, []);
  await repo.flush(true);
  assert.equal(sent[0].body.expected_revision, 12);
  assert.equal(repo.records()[0].position.last_page, 8);
  const body = structuredClone(sent[0].body);
  await repo.resolveOpen(visit.id, 19); assert.deepEqual(sent[0].body, body);
  await repo.dispose();
});
test('reader restores exact matching chapter fraction once, delayed media cannot override interaction', async () => {
  assert.equal(typeof visitRuntime.ReadingVisit, 'function');
  const repo = repository(new MemoryStore(), async () => { throw new Error('offline'); }); await repo.load();
  const restored = [];
  const visit = new visitRuntime.ReadingVisit({ repository: repo, target,
    read: async () => ({ ...canonical, last_page: 4, scroll_position: .37 }), restore: value => restored.push(value) });
  await visit.ready; visit.restoreWhenReady();
  assert.deepEqual(restored, [{ last_page: 4, scroll_position: .37 }]);
  visit.capture(7, .7, 0, true); visit.restoreWhenReady();
  assert.equal(restored.length, 1);
  visit.close();
  const other = new visitRuntime.ReadingVisit({ repository: repo, target: { ...target, chapter_id: 'different' },
    read: async () => ({ ...canonical, last_page: 9, scroll_position: .9 }), restore: value => restored.push(value) });
  await other.ready; other.restoreWhenReady();
  assert.equal(restored.length, 1, 'different chapter progress never restores');
  other.close(); await repo.dispose();
});
test('Series primary action uses pending chapter outside current chapter page without changing markers', () => {
  assert.equal(typeof model.seriesReadingAction, 'function');
  const state = { resume_chapter_slug: 'old', resume_chapter_number: 1, read_chapter_ids: ['old'], unread_count: 9 };
  const before = structuredClone(state);
  const pending = model.pendingPreview([model.createRecord({ ...target, chapter_slug: 'outside-page' }, 0, 'pending', 2)], 's');
  const action = model.seriesReadingAction('series', state, { slug: 'first' }, pending);
  assert.equal(action.href, '/read/series/outside-page');
  assert.match(action.label, /CONTINUE/); assert.match(action.status, /Local page 1.*Saving/);
  assert.deepEqual(state, before);
  assert.equal(model.seriesReadingAction('series', state, null, null).href, '/read/series/old');
});
test('immediate visit before initial disk load orders behind retained offline chapter completion', async () => {
  const store = new MemoryStore();
  const state = runtime.emptyState();
  const older = model.checkpoint(model.createRecord(target, 0, 'older', 200), 10, 1, 10, 'completion');
  state.records.older = older; store.states.set(model.scopeKey('https://a', 'alice'), state);
  let revision = 0; const commands = [];
  const repo = repository(store, async record => {
    commands.push(structuredClone(record.command));
    if (record.command.kind === 'open') assert.equal(record.command.body.expected_revision, revision);
    return { ...canonical, chapter_id: record.target.chapter_id, revision: ++revision,
      command_sequence: record.command.kind === 'commit' ? record.command.body.command_sequence : 0, command_id: record.command.body.command_id };
  });
  const visit = new visitRuntime.ReadingVisit({ repository: repo, target: { ...target, chapter_id: 'next' }, read: async () => ({ ...canonical, revision: 0 }), restore: () => {} });
  visit.capture(6, .6, 0, true); await visit.ready;
  assert.equal(repo.records().find(r => r.id === visit.id).command.depends_on, 'older');
  for (let i = 0; i < 4; i++) await repo.flush(true);
  assert.deepEqual(commands.map(command => command.kind), ['open', 'commit', 'open', 'commit']);
  assert.equal(commands[1].body.completed_page, 10); assert.equal(commands[3].body.last_page, 6);
  visit.close(); await repo.dispose();
});
test('resolved revision stays frozen through timeout, subsequent observation and reload', async () => {
  const store = new MemoryStore(); const bodies = [];
  const send = async record => { bodies.push(structuredClone(record.command.body)); throw new Error('timeout'); };
  const repo = repository(store, send); await repo.load();
  const id = repo.beginOpen(target, null); await repo.resolveOpen(id, 12); await repo.flush(true);
  await repo.resolveOpen(id, 99); await repo.flush(true); await repo.dispose();
  const reloaded = repository(store, send); await reloaded.load(); await reloaded.recoverOpens(async () => ({ ...canonical, revision: 111 })); await reloaded.flush(true);
  assert.equal(bodies.length, 3); assert.ok(bodies.every(body => JSON.stringify(body) === JSON.stringify(bodies[0])));
  assert.equal(bodies[0].expected_revision, 12); await reloaded.dispose();
});
test('reload recovers unsent revision lookup interrupted by tab exit', async () => {
  const store = new MemoryStore(); const original = repository(store, async () => canonical);
  const id = original.beginOpen(target, null); original.checkpoint(id, 8, .8, 10); await original.dispose();
  const sent = [];
  const reloaded = repository(store, async record => { sent.push(record.command); return { ...canonical, command_id: record.command.body.command_id }; });
  await reloaded.load(); await reloaded.recoverOpens(async () => ({ ...canonical, revision: 15 })); await reloaded.flush(true);
  assert.equal(sent[0].body.expected_revision, 15); assert.equal(reloaded.records()[0].position.last_page, 8);
  assert.equal(reloaded.records()[0].completed_page, 10); await reloaded.dispose();
});
test('auth suspension rejects delayed ACK even after same account resumes, explicit discard clears other tab', async () => {
  const store = new MemoryStore(); let release; let start;
  const started = new Promise(resolve => { start = resolve; });
  const notices = [];
  const make = () => new accountRuntime.ReadingAccounts({ create: account => repository(store, record => {
    start(); return new Promise(resolve => { release = () => resolve({ ...canonical, command_id: record.command.body.command_id }); });
  }, account), notify: () => {}, publish: notice => notices.push(notice), invalidateAuth: () => {} });
  const first = make(); const other = make(); await first.select('alice'); await other.select('alice');
  await first.current().open(target, 0); const original = first.current(); const flight = original.flush(true); await started;
  await first.select(null); await first.select('alice'); release(); await flight;
  assert.equal(original.hasPending(), true, 'ACK from invalidated auth generation stays unacknowledged');
  await other.current().load(); await first.clearPrivate(); other.receive(notices.at(-1));
  assert.equal(other.current(), null); assert.equal(other.warning(), '');
  await other.select('alice'); assert.deepEqual(other.current().records(), []);
});
