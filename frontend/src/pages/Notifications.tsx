import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Bell, Check, CheckCheck } from 'lucide-react';
import { api, type Notification } from '../api/client';
import { notifyNotificationsChanged } from '../hooks/useNotifications';
import { useAuth } from '../hooks/useAuth';
import { subscribeNotifications, subscribeRealtimeStatus, type RealtimeStatus } from '../realtime/client';

type RefCell<T> = { current: T };

function isCurrentNotificationRequest(
  requestId: number,
  accountId: string | null,
  loadRequestRef: RefCell<number>,
  accountRef: RefCell<string | null>,
) {
  return requestId === loadRequestRef.current && accountId === accountRef.current;
}

async function loadNotificationInbox(
  requestId: number,
  accountId: string | null,
  loadRequestRef: RefCell<number>,
  accountRef: RefCell<string | null>,
  showSpinner: boolean,
  onSuccess: (rows: Notification[]) => void,
  onFailure: () => void,
  onDone: () => void,
) {
  try {
    const data = await api.listNotifications();
    if (!isCurrentNotificationRequest(requestId, accountId, loadRequestRef, accountRef)) return;
    onSuccess(data);
  } catch {
    if (!isCurrentNotificationRequest(requestId, accountId, loadRequestRef, accountRef)) return;
    onFailure();
  } finally {
    if (showSpinner && isCurrentNotificationRequest(requestId, accountId, loadRequestRef, accountRef)) onDone();
  }
}

async function runAccountScopedNotificationMutation(
  accountId: string | null,
  accountRef: RefCell<string | null>,
  mutate: () => Promise<unknown>,
  onSuccess: () => void,
  onFailure: () => void,
) {
  try {
    await mutate();
    if (accountId !== accountRef.current) return;
    onSuccess();
  } catch {
    if (accountId !== accountRef.current) return;
    onFailure();
  }
}

export default function Notifications() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const loadRequestRef = useRef(0);
  const accountRef = useRef<string | null>(user?.id ?? null);
  accountRef.current = user?.id ?? null;

  const load = useCallback(async (showSpinner = true) => {
    const accountId = user?.id ?? null;
    const requestId = ++loadRequestRef.current;
    if (showSpinner) setLoading(true);
    setError('');
    await loadNotificationInbox(
      requestId,
      accountId,
      loadRequestRef,
      accountRef,
      showSpinner,
      setNotifications,
      () => setError('Failed to load notifications'),
      () => setLoading(false),
    );
  }, [user?.id]);

  useEffect(() => {
    loadRequestRef.current++;
    setNotifications([]);
    setError('');
    setLoading(true);
    void load();
    return () => { loadRequestRef.current++; };
  }, [user?.id, load]);
  useEffect(() => {
    let interval: number | null = null;
    const scheduleCanonicalRefresh = (realtimeStatus: RealtimeStatus) => {
      if (interval !== null) window.clearInterval(interval);
      // WebSocket is the fast path, but realtime signals are intentionally
      // ephemeral. Periodically reconcile the visible inbox with PostgreSQL so
      // a dropped live signal cannot leave this page stale indefinitely.
      const intervalMs = realtimeStatus === 'open' ? 120_000 : 30_000;
      interval = window.setInterval(() => { void load(false); }, intervalMs);
    };

    const unsubscribeNotifications = subscribeNotifications(() => { void load(false); });
    const unsubscribeStatus = subscribeRealtimeStatus(scheduleCanonicalRefresh);
    return () => {
      unsubscribeNotifications();
      unsubscribeStatus();
      if (interval !== null) window.clearInterval(interval);
    };
  }, [load]);

  const handleMarkRead = async (id: string) => {
    const accountId = accountRef.current;
    const before = notifications;
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    setError('');
    await runAccountScopedNotificationMutation(
      accountId,
      accountRef,
      () => api.markRead(id),
      notifyNotificationsChanged,
      () => {
        // Roll back optimistic presentation if persistence failed.
        setNotifications(before);
        setError('Failed to mark notification as read. Please retry.');
      },
    );
  };

  const handleMarkAllRead = async () => {
    const accountId = accountRef.current;
    const before = notifications;
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
    setError('');
    await runAccountScopedNotificationMutation(
      accountId,
      accountRef,
      () => api.markAllRead(),
      notifyNotificationsChanged,
      () => {
        setNotifications(before);
        setError('Failed to mark notifications as read. Please retry.');
      },
    );
  };

  const hasUnread = notifications.some(n => !n.is_read);

  return (
    <div className="w-full min-w-0 max-w-2xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="min-w-0 font-display text-xl sm:text-2xl font-bold flex items-center gap-2">
          <Bell size={24} /> Notifications
        </h1>
        {hasUnread && (
          <button onClick={handleMarkAllRead} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-ink-800 hover:bg-ink-700 text-sm transition-colors">
            <CheckCheck size={16} /> Mark all read
          </button>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-amber-700/50 bg-amber-950/25 px-4 py-3 text-sm text-amber-200">
          {error} <button type="button" onClick={() => void load()} className="ml-2 underline">Retry</button>
        </div>
      )}

      {loading && notifications.length === 0 ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-20 rounded-xl" />)}
        </div>
      ) : notifications.length === 0 ? (
        <div className="text-center py-12 text-ink-400">
          <p>{error ? 'Notifications are temporarily unavailable.' : 'No notifications yet'}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {notifications.map((n) => (
            <div key={n.id} className={`flex min-w-0 items-start gap-3 p-3 sm:p-4 rounded-xl border transition-colors ${
              n.is_read ? 'bg-ink-900 border-ink-800' : 'bg-brand-900/20 border-brand-700/50'
            }`}>
              <div className="flex-1 min-w-0">
                <p className="mreader-break-anywhere text-ink-200 text-sm mb-1">{n.message}</p>
                {n.series_slug && n.chapter_slug ? (
                  <Link to={`/read/${n.series_slug}/${n.chapter_slug}`} className="mreader-break-anywhere text-brand-400 hover:underline text-xs">
                    {n.series_title || 'Series'}{n.chapter_number !== null ? ` — Ch. ${n.chapter_number}` : ''}
                  </Link>
                ) : n.series_title ? (
                  <span className="mreader-break-anywhere text-ink-400 text-xs">{n.series_title}</span>
                ) : (
                  <span className="text-ink-500 text-[11px] uppercase tracking-wide">{n.kind.replace(/[._-]+/g, ' ')}</span>
                )}
                <p className="text-ink-500 text-xs mt-1">{new Date(n.created_at).toLocaleString()}</p>
              </div>
              {!n.is_read && (
                <button onClick={() => handleMarkRead(n.id)} className="shrink-0 p-2 text-ink-400 hover:text-brand-400 transition-colors">
                  <Check size={18} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
