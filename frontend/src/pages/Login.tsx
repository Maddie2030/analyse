import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username_or_email: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login({ ...form, turnstile_token: '' });
      navigate('/');
    } catch (err: any) {
      setError(err?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex items-center justify-center px-3 sm:px-4 animate-fade-in">
      <div className="w-full min-w-0 max-w-md">
        <h1 className="font-display text-3xl font-bold mb-2 text-center">Welcome back</h1>
        <p className="text-ink-400 text-center mb-6">Sign in to your account</p>

        {error && <div className="bg-red-900/30 border border-red-700/50 mreader-break-anywhere text-red-300 px-4 py-3 rounded-lg mb-4 text-sm">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-ink-300 mb-1">Username or Email</label>
            <input
              type="text"
              value={form.username_or_email}
              onChange={(e) => setForm({ ...form, username_or_email: e.target.value })}
              required
              className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="block text-sm text-ink-300 mb-1">Password</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
              className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
            />
          </div>
          <button type="submit" disabled={loading} className="w-full py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-xl transition-colors">
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-ink-400 mt-4 text-sm">
          Don't have an account? <Link to="/register" className="text-brand-400 hover:underline">Sign up</Link>
        </p>
      </div>
    </div>
  );
}
