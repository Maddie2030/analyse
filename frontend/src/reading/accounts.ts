import type { ReadingRepository } from './repository.ts';
export type ReadingAuthNotice = { kind: 'auth'; account: string | null } | { kind: 'discard'; accounts: string[] };
type Options = { create: (account: string | null) => ReadingRepository; notify: () => void;
  publish: (notice: ReadingAuthNotice) => void; invalidateAuth: () => void };
// Suspended repositories remain owned here even when IndexedDB cannot save them.
// A broadcast is a suspension hint, never proof of an authenticated identity.
export class ReadingAccounts {
  private options: Options;
  private repositories = new Map<string | null, ReadingRepository>();
  private selected: ReadingRepository | null = null;
  private generation = 0;
  constructor(options: Options) { this.options = options; }
  current() { return this.selected; }
  async select(account: string | null) {
    const previous = this.selected?.account();
    const generation = ++this.generation;
    if (previous !== account) this.selected?.suspend();
    let repository = this.repositories.get(account);
    if (!repository?.isActive()) {
      repository = this.options.create(account);
      this.repositories.set(account, repository);
    }
    this.selected = repository;
    if (previous !== account) this.options.publish({ kind: 'auth', account });
    this.options.notify();
    await repository.load();
    if (generation !== this.generation) return;
    repository.resume();
    await repository.reauthenticate();
    this.options.notify();
  }
  invalidate() {
    this.generation++;
    this.selected?.suspend();
    this.selected = null;
    this.options.notify();
    this.options.invalidateAuth();
  }
  receive(notice: ReadingAuthNotice) {
    if (notice.kind === 'discard') {
      // The originating tab has already written durable epoch tombstones.
      for (const account of notice.accounts) {
        const repository = this.repositories.get(account);
        if (repository) { void repository.releaseCleared(); this.repositories.delete(account); }
      }
      this.invalidate();
    } else if (notice.kind === 'auth' && notice.account !== this.selected?.account()) this.invalidate();
  }
  warning() {
    const held = [...this.repositories.entries()].filter(([account, repo]) => account !== null && repo !== this.selected && repo.hasPending());
    if (!held.length) return '';
    return held.some(([, repo]) => repo.hasVolatile() || repo.storageError)
      ? 'Reading sync paused for a previous sign-in. Unsynced changes are only in memory. Keep this tab open and sign in to the same account to save them.'
      : 'Reading sync paused for a previous sign-in. Sign in to the same account to save your pending changes.';
  }
  hasPrivatePending() { return [...this.repositories.entries()].some(([account, repo]) => account !== null && repo.hasPending()); }
  async clearPrivate() {
    const accounts: string[] = [];
    for (const [account, repo] of this.repositories) if (account !== null) {
      await repo.clear(); this.repositories.delete(account); accounts.push(account);
    }
    if (this.selected?.account() !== null) this.selected = null;
    this.options.publish({ kind: 'discard', accounts });
    this.options.notify();
  }
}
