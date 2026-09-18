export type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'closed';

export const REALTIME_AUTH_INVALIDATED_EVENT = 'mreader:realtime-auth-invalidated';
const REALTIME_SESSION_INVALID_CLOSE_CODE = 4001;

export interface RealtimeNotificationPayload {
  id: string;
  kind: string;
  message: string;
  series_id: string | null;
  chapter_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationCreatedSignal {
  type: 'notification.created';
  notification: RealtimeNotificationPayload;
  unread_count: number;
}

export type CommentChangedEvent =
  | { type: 'created'; comment: import('../api/client').Comment }
  | { type: 'deleted'; comment_id: string };

export interface CommentChangedSignal {
  type: 'comment.changed';
  series_id: string;
  chapter_id: string | null;
  event: CommentChangedEvent;
}

type EventListener<T = unknown> = (payload: T) => void;
type StatusListener = (status: RealtimeStatus) => void;

type CommentSubscription = {
  seriesId: string;
  chapterId: string | null;
  listeners: Set<EventListener<CommentChangedSignal>>;
};

const eventListeners = new Map<string, Set<EventListener>>();
const commentSubscriptions = new Map<string, CommentSubscription>();
const statusListeners = new Set<StatusListener>();

let socket: WebSocket | null = null;
let reconnectTimer: number | null = null;
let reconnectAttempt = 0;
let status: RealtimeStatus = 'idle';

function commentKey(seriesId: string, chapterId: string | null | undefined): string {
  return `${seriesId}:${chapterId || 'series'}`;
}

function websocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/realtime/ws`;
}

function hasDemand(): boolean {
  for (const listeners of eventListeners.values()) {
    if (listeners.size > 0) return true;
  }
  for (const subscription of commentSubscriptions.values()) {
    if (subscription.listeners.size > 0) return true;
  }
  return false;
}

function setStatus(next: RealtimeStatus) {
  if (status === next) return;
  status = next;
  for (const listener of [...statusListeners]) {
    try { listener(next); } catch { /* one observer must not break realtime */ }
  }
}

function clearReconnectTimer() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect(delayOverride?: number) {
  clearReconnectTimer();
  if (!hasDemand() || typeof window === 'undefined' || typeof WebSocket === 'undefined') {
    setStatus(hasDemand() ? 'closed' : 'idle');
    return;
  }
  const baseDelay = delayOverride ?? Math.min(15_000, 750 * (2 ** Math.min(reconnectAttempt, 5)));
  // Full-fleet reconnects after a gateway/realtime restart should not land in
  // the same millisecond. A small positive jitter preserves backoff while
  // smoothing Redis/session and WebSocket upgrade load.
  const delay = delayOverride !== undefined
    ? baseDelay
    : Math.round(baseDelay * (0.85 + Math.random() * 0.30));
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function sendCommand(value: unknown) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  try {
    socket.send(JSON.stringify(value));
  } catch {
    // onclose/reconnect will restore subscriptions.
  }
}

function sendCommentSubscription(subscription: CommentSubscription, subscribe: boolean) {
  sendCommand({
    type: subscribe ? 'subscribe.comments' : 'unsubscribe.comments',
    series_id: subscription.seriesId,
    chapter_id: subscription.chapterId,
  });
}

function resubscribeComments() {
  for (const subscription of commentSubscriptions.values()) {
    if (subscription.listeners.size > 0) sendCommentSubscription(subscription, true);
  }
}

function dispatchMessage(raw: string) {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return;
  }
  if (!payload || typeof payload !== 'object') return;
  const type = String((payload as { type?: unknown }).type || '');
  if (!type) return;

  const listeners = eventListeners.get(type);
  if (listeners) {
    for (const listener of [...listeners]) {
      try { listener(payload); } catch { /* isolate observers */ }
    }
  }

  if (type === 'comment.changed') {
    const signal = payload as CommentChangedSignal;
    if (!signal.series_id) return;
    const subscription = commentSubscriptions.get(commentKey(signal.series_id, signal.chapter_id));
    if (!subscription) return;
    for (const listener of [...subscription.listeners]) {
      try { listener(signal); } catch { /* isolate observers */ }
    }
  }
}

function connect() {
  if (typeof window === 'undefined' || typeof WebSocket === 'undefined') {
    setStatus(hasDemand() ? 'closed' : 'idle');
    return;
  }
  if (!hasDemand()) {
    setStatus('idle');
    return;
  }
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

  clearReconnectTimer();
  setStatus('connecting');
  const ws = new WebSocket(websocketUrl());
  socket = ws;

  ws.onopen = () => {
    if (socket !== ws) return;
    reconnectAttempt = 0;
    setStatus('open');
    resubscribeComments();
  };

  ws.onmessage = (event) => {
    if (socket !== ws || typeof event.data !== 'string') return;
    dispatchMessage(event.data);
  };

  ws.onerror = () => {
    // Browsers intentionally expose little WebSocket error detail. Closing the
    // socket moves the client into the reconnect/fallback path.
    try { ws.close(); } catch { /* already closing */ }
  };

  ws.onclose = (event) => {
    if (socket !== ws) return;
    if (event.code === REALTIME_SESSION_INVALID_CLOSE_CODE) {
      window.dispatchEvent(new Event(REALTIME_AUTH_INVALIDATED_EVENT));
    }
    socket = null;
    reconnectAttempt += 1;
    if (!hasDemand()) {
      setStatus('idle');
      return;
    }
    setStatus('closed');
    scheduleReconnect();
  };
}

function ensureConnected() {
  if (!hasDemand()) return;
  connect();
}

function closeIfUnused() {
  if (hasDemand()) return;
  clearReconnectTimer();
  const current = socket;
  socket = null;
  if (current) {
    try { current.close(1000, 'no realtime subscribers'); } catch { /* ignore */ }
  }
  reconnectAttempt = 0;
  setStatus('idle');
}

export function getRealtimeStatus(): RealtimeStatus {
  return status;
}

export function subscribeRealtimeStatus(listener: StatusListener): () => void {
  statusListeners.add(listener);
  listener(status);
  return () => { statusListeners.delete(listener); };
}

export function subscribeRealtime<T>(type: string, listener: EventListener<T>): () => void {
  const listeners = eventListeners.get(type) || new Set<EventListener>();
  listeners.add(listener as EventListener);
  eventListeners.set(type, listeners);
  ensureConnected();
  return () => {
    const current = eventListeners.get(type);
    current?.delete(listener as EventListener);
    if (current && current.size === 0) eventListeners.delete(type);
    closeIfUnused();
  };
}

export function subscribeNotifications(listener: EventListener<NotificationCreatedSignal>): () => void {
  return subscribeRealtime<NotificationCreatedSignal>('notification.created', listener);
}

export function subscribeComments(
  seriesId: string,
  chapterId: string | null | undefined,
  listener: EventListener<CommentChangedSignal>,
): () => void {
  const normalizedChapterId = chapterId || null;
  const key = commentKey(seriesId, normalizedChapterId);
  let subscription = commentSubscriptions.get(key);
  const wasEmpty = !subscription || subscription.listeners.size === 0;
  if (!subscription) {
    subscription = { seriesId, chapterId: normalizedChapterId, listeners: new Set() };
    commentSubscriptions.set(key, subscription);
  }
  subscription.listeners.add(listener);
  ensureConnected();
  if (!wasEmpty && socket?.readyState === WebSocket.OPEN) {
    // The server already has this logical subscription; no duplicate command.
  } else if (socket?.readyState === WebSocket.OPEN) {
    sendCommentSubscription(subscription, true);
  }

  return () => {
    const current = commentSubscriptions.get(key);
    if (!current) return;
    current.listeners.delete(listener);
    if (current.listeners.size === 0) {
      if (socket?.readyState === WebSocket.OPEN) sendCommentSubscription(current, false);
      commentSubscriptions.delete(key);
    }
    closeIfUnused();
  };
}

export function resetRealtimeConnection() {
  if (typeof window === 'undefined') return;
  clearReconnectTimer();
  const current = socket;
  socket = null;
  if (current) {
    try { current.close(1000, 'authentication changed'); } catch { /* ignore */ }
  }
  reconnectAttempt = 0;
  if (hasDemand()) {
    setStatus('closed');
    scheduleReconnect(0);
  } else {
    setStatus('idle');
  }
}
