import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../api/client';
import { useAuth } from './useAuth';
import { subscribeNotifications, subscribeRealtimeStatus, type RealtimeStatus } from '../realtime/client';

const NOTIFICATIONS_CHANGED_EVENT = 'mreader:notifications-changed';

export function notifyNotificationsChanged() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED_EVENT));
  }
}

export function useNotifications() {
  const { user } = useAuth();
  const [unreadCount, setUnreadCount] = useState(0);
  const refreshGeneration = useRef(0);
  const accountRef = useRef<string | null>(user?.id ?? null);
  accountRef.current = user?.id ?? null;

  const refresh = useCallback(async () => {
    const accountId = user?.id ?? null;
    const generation = ++refreshGeneration.current;
    if (!accountId) {
      if (generation === refreshGeneration.current && accountRef.current === null) setUnreadCount(0);
      return;
    }
    try {
      const data = await api.notificationCount();
      if (generation !== refreshGeneration.current || accountId !== accountRef.current) return;
      setUnreadCount(data.unread);
    } catch {
      // A transient Social/Gateway outage is not evidence that all alerts were
      // read. Preserve the last known count until a successful refresh.
    }
  }, [user?.id]);

  useEffect(() => {
    refreshGeneration.current++;
    void refresh();
    if (!user) return;

    let interval: number | null = null;
    const scheduleFallbackRefresh = (realtimeStatus: RealtimeStatus) => {
      if (interval !== null) window.clearInterval(interval);
      // WebSocket delivery is primary. A slow canonical refresh remains as a
      // recovery path for missed ephemeral signals or long broker outages.
      const intervalMs = realtimeStatus === 'open' ? 120_000 : 30_000;
      interval = window.setInterval(() => { void refresh(); }, intervalMs);
    };

    const onChanged = () => { void refresh(); };
    window.addEventListener(NOTIFICATIONS_CHANGED_EVENT, onChanged);
    const accountId = user.id;
    const unsubscribeNotifications = subscribeNotifications((signal) => {
      if (accountRef.current !== accountId) return;
      if (Number.isFinite(signal.unread_count)) setUnreadCount(Math.max(0, signal.unread_count));
      else void refresh();
    });
    const unsubscribeStatus = subscribeRealtimeStatus(scheduleFallbackRefresh);

    return () => {
      refreshGeneration.current++;
      window.removeEventListener(NOTIFICATIONS_CHANGED_EVENT, onChanged);
      unsubscribeNotifications();
      unsubscribeStatus();
      if (interval !== null) window.clearInterval(interval);
    };
  }, [refresh, user]);

  return { unreadCount, refresh };
}
