import { api, apiErrorStatus, resetPersonalRequests } from '../api/client';
import { IndexedReadingStore } from './indexedDB';
import { ReadingRepository } from './repository';
import { ReadingAccounts } from './accounts';
export const READING_CONFIRMED_EVENT = 'mreader:reading-confirmed';
export const READING_AUTH_INVALIDATED_EVENT = 'mreader:reading-auth-invalidated';
const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('mreader-reading-v1') : null;
const store = new IndexedReadingStore((scope, confirmed) => channel?.postMessage({ scope, confirmed }));
const listeners = new Set<() => void>();
export const subscribeReading = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
let version = 0;
export const readingVersion = () => version;
function changed(confirmed: boolean) {
  version++;
  listeners.forEach(fn => fn());
  if (confirmed) resetPersonalRequests();
  if (confirmed) window.dispatchEvent(new Event(READING_CONFIRMED_EVENT));
}
const accounts: ReadingAccounts = new ReadingAccounts({
  notify: () => { resetPersonalRequests(); changed(false); },
  publish: notice => channel?.postMessage(notice),
  invalidateAuth: () => window.dispatchEvent(new Event(READING_AUTH_INVALIDATED_EVENT)),
  create: account => new ReadingRepository({ store, origin: location.origin, account, uuid: () => crypto.randomUUID(), now: Date.now,
    notify: changed,
    send: async record => {
      const command = record.command!;
      try {
        if (account === null) throw { status: 401 };
        return command.kind === 'open'
          ? await api.recordChapterOpen(account, record.target.series_slug, record.target.chapter_slug, command.body)
          : await api.commitProgress(account, record.target.series_slug, record.target.chapter_slug, command.body, true);
      } catch (error) {
        const status = apiErrorStatus(error);
        if ((status === 401 || status === 403) && accounts.current()?.account() === account) accounts.invalidate();
        throw Object.assign(new Error('Reading sync failed'), { status });
      }
    },
  }),
});
export const readingRepository = () => accounts.current();
export const readingAccountWarning = () => accounts.warning();
export const hasPrivatePendingReading = () => accounts.hasPrivatePending();
export const clearPrivateReading = () => accounts.clearPrivate();
export function setReadingAccount(next: string | null) {
  void accounts.select(next).then(async () => {
    const repository = accounts.current();
    if (repository?.account() !== next) return;
    await repository?.recoverOpens(next === null ? undefined : target => api.getProgress(next, target.series_slug, target.chapter_slug));
    await repository?.flush(true);
  });
}
channel?.addEventListener('message', event => {
  if (event.data?.kind === 'auth' || event.data?.kind === 'discard') { accounts.receive(event.data); return; }
  const repository = accounts.current();
  if (event.data?.scope === repository?.scope) void repository?.load().then(() => changed(Boolean(event.data.confirmed)));
});
window.setInterval(() => { void accounts.current()?.flush(); }, 30_000);
window.setInterval(() => accounts.current()?.retryDue(), 1000);
window.addEventListener('online', () => { void accounts.current()?.flush(true); });
window.addEventListener('pagehide', () => { void accounts.current()?.flush(); });
document.addEventListener('visibilitychange', () => { void accounts.current()?.flush(document.visibilityState === 'visible'); });
