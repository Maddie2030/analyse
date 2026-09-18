import { Reply, Trash2 } from 'lucide-react';
import type { Comment, User } from '../api/client';

function relativeTime(value: string): string {
  const diff = Math.floor((Date.now() - new Date(value).getTime()) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(value).toLocaleDateString();
}

function UserAvatar({ username }: { username: string }) {
  const initials = username.split(/[\s_]+/).map(w => w[0]).filter(Boolean).slice(0, 2).join('') || '?';
  return <div className="w-9 h-9 rounded-full bg-brand-600/20 text-brand-300 flex items-center justify-center text-sm font-medium flex-shrink-0">{initials.toUpperCase()}</div>;
}

interface Props {
  comment: Comment;
  repliesByParent: Map<string, Comment[]>;
  currentUser: User | null;
  onReply: (comment: Comment) => void;
  onDelete: (comment: Comment) => void;
  depth?: number;
}

export default function CommentItem({ comment, repliesByParent, currentUser, onReply, onDelete, depth = 0 }: Props) {
  const replies = repliesByParent.get(comment.id) || [];
  return (
    <article className={depth > 0 ? 'min-w-0 mt-3 border-l border-ink-800 pl-2 sm:pl-4' : 'min-w-0'}>
      <div className="flex gap-3">
        <UserAvatar username={comment.author_username} />
        <div className="flex-1 min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 mb-1">
            <span className="mreader-break-anywhere min-w-0 text-sm font-medium text-ink-200">{comment.author_username}</span>
            <time dateTime={comment.created_at} className="text-xs text-ink-500">{relativeTime(comment.created_at)}</time>
            {depth > 0 && <span className="text-[10px] text-ink-600">reply level {depth}</span>}
          </div>
          <p className="text-ink-300 text-sm whitespace-pre-wrap break-words mb-2">{comment.content}</p>
          <div className="flex items-center gap-3">
            {currentUser && depth < 4 && (
              <button onClick={() => onReply(comment)} className="flex items-center gap-1 text-xs text-ink-500 hover:text-brand-400 transition-colors"><Reply size={14} /> Reply</button>
            )}
            {currentUser?.id === comment.user_id && (
              <button onClick={() => onDelete(comment)} className="flex items-center gap-1 text-xs text-ink-500 hover:text-red-400 transition-colors"><Trash2 size={14} /> Delete</button>
            )}
          </div>
        </div>
      </div>
      {replies.length > 0 && (
        <div className={depth === 0 ? 'ml-4 sm:ml-12 mt-3 space-y-3' : 'ml-2 sm:ml-5 mt-3 space-y-3'}>
          {replies.map(reply => (
            <CommentItem key={reply.id} comment={reply} repliesByParent={repliesByParent} currentUser={currentUser} onReply={onReply} onDelete={onDelete} depth={depth + 1} />
          ))}
        </div>
      )}
    </article>
  );
}
