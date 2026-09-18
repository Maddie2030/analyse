import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Activity, LoaderCircle, MessageCircle, Send } from 'lucide-react';
import { api, type Comment } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import CommentItem from './CommentItem';
import { getRealtimeStatus, subscribeComments, subscribeRealtimeStatus, type CommentChangedSignal } from '../realtime/client';

interface Props {
  seriesId: string;
  chapterId?: string;
  title?: string;
}

export default function CommentSection({ seriesId, chapterId, title = 'Discussion' }: Props) {
  const { user } = useAuth();
  const [comments, setComments] = useState<Comment[]>([]);
  const [content, setContent] = useState('');
  const [replyingTo, setReplyingTo] = useState<Comment | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const loadComments = useCallback(async (showSpinner = true) => {
    if (showSpinner) setLoading(true);
    setError('');
    try {
      const data = await api.listComments({ seriesId, chapterId });
      setComments(data.items);
    } catch {
      setError('Failed to load comments');
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, [seriesId, chapterId]);

  useEffect(() => { void loadComments(); }, [loadComments]);

  useEffect(() => {
    let reconcileTimer: number | null = null;
    let connectingTimer: number | null = null;

    const removeCommentTree = (items: Comment[], rootId: string): Comment[] => {
      const removed = new Set<string>([rootId]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const item of items) {
          if (item.parent_id && removed.has(item.parent_id) && !removed.has(item.id)) {
            removed.add(item.id);
            changed = true;
          }
        }
      }
      return items.filter(item => !removed.has(item.id));
    };

    const applySignal = (signal: CommentChangedSignal) => {
      const event = signal.event;
      if (event.type === 'created') {
        setComments(prev => {
          const index = prev.findIndex(item => item.id === event.comment.id);
          if (index === -1) return [...prev, event.comment];
          const next = [...prev];
          next[index] = event.comment;
          return next;
        });
        return;
      }
      if (event.type === 'deleted') {
        setComments(prev => removeCommentTree(prev, event.comment_id));
      }
    };

    const stopReconcile = () => {
      if (reconcileTimer !== null) {
        window.clearInterval(reconcileTimer);
        reconcileTimer = null;
      }
    };
    const clearConnectingTimer = () => {
      if (connectingTimer !== null) {
        window.clearTimeout(connectingTimer);
        connectingTimer = null;
      }
    };
    const startReconcile = () => {
      if (reconcileTimer !== null) return;
      // HTTP is a low-rate recovery path only. Realtime deltas are authoritative
      // while the WebSocket is connected, so we do not create a second Redis
      // subscriber per browser through SSE.
      reconcileTimer = window.setInterval(() => { void loadComments(false); }, 30_000);
    };

    const unsubscribeComments = subscribeComments(seriesId, chapterId, applySignal);
    const unsubscribeStatus = subscribeRealtimeStatus((realtimeStatus) => {
      if (realtimeStatus === 'open') {
        clearConnectingTimer();
        stopReconcile();
        // Reconcile once after reconnect in case events were missed while offline.
        void loadComments(false);
      } else if (realtimeStatus === 'closed') {
        clearConnectingTimer();
        startReconcile();
      } else if (realtimeStatus === 'connecting') {
        clearConnectingTimer();
        connectingTimer = window.setTimeout(() => {
          connectingTimer = null;
          if (getRealtimeStatus() !== 'open') startReconcile();
        }, 5_000);
      } else {
        clearConnectingTimer();
        stopReconcile();
      }
    });

    return () => {
      unsubscribeComments();
      unsubscribeStatus();
      clearConnectingTimer();
      stopReconcile();
    };
  }, [seriesId, chapterId, loadComments]);

  const repliesByParent = useMemo(() => {
    const map = new Map<string, Comment[]>();
    comments.filter(c => c.parent_id).forEach(c => {
      const list = map.get(c.parent_id!) || [];
      list.push(c);
      map.set(c.parent_id!, list);
    });
    return map;
  }, [comments]);

  const topLevelComments = useMemo(() => comments.filter(c => !c.parent_id), [comments]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = content.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const created = await api.createComment({
        content: trimmed,
        series_id: seriesId,
        chapter_id: chapterId || null,
        parent_id: replyingTo?.id || null,
      });
      setComments(prev => [...prev, created]);
      setContent('');
      setReplyingTo(null);
    } catch {
      setError('Failed to post comment');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (comment: Comment) => {
    await api.deleteComment(comment.id);
    // Apply the local result immediately. The realtime delete event is
    // idempotent and will converge other tabs/clients without a full reload.
    setComments(prev => {
      const removed = new Set<string>([comment.id]);
      let changed = true;
      while (changed) {
        changed = false;
        for (const item of prev) {
          if (item.parent_id && removed.has(item.parent_id) && !removed.has(item.id)) {
            removed.add(item.id);
            changed = true;
          }
        }
      }
      return prev.filter(item => !removed.has(item.id));
    });
  };

  return (
    <div className="w-full min-w-0 max-w-3xl" aria-labelledby="comments-heading">
      <div className="flex min-w-0 flex-wrap items-center gap-2 mb-4">
        <MessageCircle size={20} className="text-brand-400" />
        <h2 id="comments-heading" className="font-display text-xl font-bold">{title}</h2>
        <span className="text-ink-400 text-sm">({comments.length})</span>
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-green-400"><Activity size={12} /> live</span>
      </div>

      {user ? (
        <form onSubmit={handleSubmit} className="mb-6">
          {replyingTo && (
            <div className="flex min-w-0 flex-wrap items-center gap-2 mb-2 text-sm text-ink-400">
              <span className="min-w-0 break-words">Replying to <strong className="mreader-break-anywhere text-ink-200">{replyingTo.author_username}</strong></span>
              <button type="button" onClick={() => { setReplyingTo(null); setContent(''); }} className="text-brand-400 hover:underline">Cancel</button>
            </div>
          )}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            maxLength={2000}
            placeholder={replyingTo ? `Reply to ${replyingTo.author_username}...` : 'Share your thoughts...'}
            rows={3}
            className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 placeholder-ink-500 focus:border-brand-500 focus:outline-none transition-colors resize-none"
          />
          <div className="flex justify-end mt-2">
            <button type="submit" disabled={!content.trim() || submitting} className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-lg text-sm transition-colors">
              {submitting ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />} Post
            </button>
          </div>
        </form>
      ) : (
        <div className="bg-ink-900 border border-ink-800 rounded-xl p-4 mb-6 text-center text-ink-400 text-sm">
          <Link to="/login" className="text-brand-400 hover:underline">Sign in</Link> to join the discussion
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-3 rounded-lg mb-4 text-sm flex flex-wrap items-center justify-between gap-2">
          <span>{error}</span>
          <button onClick={loadComments} className="text-brand-400 hover:underline text-sm">Retry</button>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => <div key={i} className="skeleton h-24 rounded-xl" />)}
        </div>
      ) : topLevelComments.length === 0 ? (
        <p className="text-ink-400 text-center py-8">No comments yet. Be the first!</p>
      ) : (
        <div className="space-y-4">
          {topLevelComments.map((c) => (
            <CommentItem
              key={c.id}
              comment={c}
              repliesByParent={repliesByParent}
              currentUser={user}
              onReply={(comment) => { setReplyingTo(comment); setContent(''); }}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
