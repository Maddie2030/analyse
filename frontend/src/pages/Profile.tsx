import { useEffect, useState } from 'react';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { api, apiErrorMessage } from '../api/client';
import { AVATAR_OPTIONS, avatarSrc, normalizeAvatarKey, type AvatarKey } from '../utils/avatars';


const PROFILE_AVATAR_OPTIONS = [
  { key: 'skull' as const, label: 'Skull', description: 'Default reader mark.' },
  ...AVATAR_OPTIONS,
];

export default function Profile() {
  const { user, refresh } = useAuth();
  const [form, setForm] = useState({
    username: user?.username || '',
    email: user?.email || '',
    avatar_key: normalizeAvatarKey(user?.avatar_key),
  });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!user) return;
    setForm({
      username: user.username || '',
      email: user.email || '',
      avatar_key: normalizeAvatarKey(user.avatar_key),
    });
  }, [user?.id, user?.username, user?.email, user?.avatar_key]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess(false);
    try {
      await api.updateProfile({ avatar_key: form.avatar_key });
      await refresh();
      setSuccess(true);
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Could not update profile.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] px-3 sm:px-4 py-8 animate-fade-in">
      <div className="w-full min-w-0 max-w-3xl mx-auto">
        <div className="flex items-center gap-4 mb-7">
          <div className="relative shrink-0">
            <img
              src={avatarSrc(form.avatar_key)}
              alt="Selected profile avatar"
              className="h-20 w-20 rounded-full border-2 border-brand-500/30 bg-ink-950 object-cover shadow-lg shadow-brand-950/30"
            />
            {user?.role === 'admin' && (
              <span className="absolute -right-2 -bottom-2 rounded-full border border-amber-500/60 bg-amber-950 p-1.5 text-amber-300" title="Administrator">
                <ShieldCheck size={16} />
              </span>
            )}
          </div>
          <div className="min-w-0">
            <h1 className="font-display text-3xl font-bold">Profile</h1>
            <p className="mt-1 text-sm text-ink-400">Choose how your reader profile appears. Username and email are fixed account identifiers.</p>
          </div>
        </div>

        {error && <div className="bg-red-900/30 border border-red-700/50 mreader-break-anywhere text-red-300 px-4 py-3 rounded-lg mb-4 text-sm">{error}</div>}
        {success && <div className="bg-green-900/30 border border-green-700/50 text-green-300 px-4 py-3 rounded-lg mb-4 text-sm">Profile updated successfully</div>}

        <form onSubmit={handleSubmit} className="space-y-6">
          <section className="rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5">
            <div className="mb-4">
              <h2 className="font-display text-lg font-semibold">Avatar</h2>
              <p className="text-xs text-ink-500 mt-1">Choose from eight themed identities. Skull remains the default avatar until you select another.</p>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 auto-rows-fr items-stretch gap-3">
              {PROFILE_AVATAR_OPTIONS.map((option) => (
                <button
                  type="button"
                  key={option.key}
                  onClick={() => setForm((current) => ({ ...current, avatar_key: option.key }))}
                  aria-pressed={form.avatar_key === option.key}
                  className={`relative h-full min-h-[16rem] rounded-xl border p-3 transition flex flex-col items-center ${form.avatar_key === option.key ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/25' : 'border-ink-800 bg-ink-950/50 hover:border-ink-700'}`}
                >
                  <div className="h-36 w-full flex items-center justify-center shrink-0">
                    <img
                      src={avatarSrc(option.key)}
                      alt={`${option.label} avatar`}
                      className="h-32 w-32 rounded-full object-cover border border-ink-700/70"
                    />
                  </div>
                  <div className="h-10 w-full flex items-center justify-center text-sm font-medium text-center leading-5">{option.label}</div>
                  <div className="h-12 w-full flex items-start justify-center text-[11px] leading-4 text-ink-500 text-center overflow-hidden">{option.description}</div>
                  <div className={`h-4 mt-auto text-center text-[10px] font-semibold uppercase tracking-wide ${form.avatar_key === option.key ? 'text-brand-300' : 'text-transparent'}`}>
                    Selected
                  </div>
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-ink-800 bg-ink-900/60 p-4 sm:p-5 space-y-4">
            <div>
              <label className="flex items-center gap-2 text-sm text-ink-300 mb-1">Username <LockKeyhole size={13} className="text-ink-500" /></label>
              <input type="text" value={form.username} readOnly aria-readonly="true" className="w-full cursor-not-allowed px-4 py-3 bg-ink-950/70 border border-ink-800 rounded-xl text-ink-300 outline-none" />
            </div>
            <div>
              <label className="flex items-center gap-2 text-sm text-ink-300 mb-1">Email <LockKeyhole size={13} className="text-ink-500" /></label>
              <input type="email" value={form.email} readOnly aria-readonly="true" className="w-full cursor-not-allowed px-4 py-3 bg-ink-950/70 border border-ink-800 rounded-xl text-ink-300 outline-none" />
            </div>
            <p className="text-xs text-ink-500">Account identifiers cannot be changed from profile settings.</p>
          </section>

          <button type="submit" disabled={loading} className="w-full py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-xl transition-colors">
            {loading ? 'Saving...' : 'Save profile'}
          </button>
        </form>
      </div>
    </div>
  );
}
