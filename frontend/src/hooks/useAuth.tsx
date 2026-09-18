import { createContext, useContext, useEffect, useState, useCallback, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { api, apiErrorStatus, type User } from '../api/client';
import { readingRepository, setReadingAccount, READING_AUTH_INVALIDATED_EVENT, readingAccountWarning, subscribeReading, readingVersion, hasPrivatePendingReading, clearPrivateReading } from '../reading/browser';
import { clearProtectedAssetCache } from '../reader/protectedAssetCache';
import { REALTIME_AUTH_INVALIDATED_EVENT, resetRealtimeConnection } from '../realtime/client';

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (body: any) => Promise<User>;
  register: (body: any) => Promise<User>;
  logout: () => Promise<boolean>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const authGeneration = useRef(0);
  useSyncExternalStore(subscribeReading, readingVersion);
  const readingWarning = readingAccountWarning();

  const refresh = useCallback(async () => {
    const generation = ++authGeneration.current;
    try {
      const profile = await api.getProfile();
      if (generation !== authGeneration.current) return;
      setReadingAccount(profile.id);
      setUser(profile);
      resetRealtimeConnection();
    } catch (error) {
      if (generation !== authGeneration.current) return;
      const status = apiErrorStatus(error);
      // Only an authoritative auth response should clear the local session
      // state. A temporary gateway/Auth outage must not make a signed-in user
      // appear logged out across the entire UI.
      if (status === 401 || status === 403) {
        setReadingAccount(null);
        setUser(null);
        resetRealtimeConnection();
      }
    } finally {
      if (generation !== authGeneration.current) return;
      if (!readingRepository()) setReadingAccount(null);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const onRealtimeAuthInvalidated = () => { void refresh(); };
    const onReadingAuthInvalidated = () => { setUser(null); void refresh(); };
    window.addEventListener(REALTIME_AUTH_INVALIDATED_EVENT, onRealtimeAuthInvalidated);
    window.addEventListener(READING_AUTH_INVALIDATED_EVENT, onReadingAuthInvalidated);
    return () => {
      window.removeEventListener(REALTIME_AUTH_INVALIDATED_EVENT, onRealtimeAuthInvalidated);
      window.removeEventListener(READING_AUTH_INVALIDATED_EVENT, onReadingAuthInvalidated);
    };
  }, [refresh]);

  const login = useCallback(async (body: any) => {
    const generation = ++authGeneration.current;
    const profile = await api.login(body);
    if (generation !== authGeneration.current) return profile;
    setReadingAccount(profile.id);
    setUser(profile);
    resetRealtimeConnection();
    return profile;
  }, []);

  const register = useCallback(async (body: any) => {
    const generation = ++authGeneration.current;
    const profile = await api.register(body);
    if (generation !== authGeneration.current) return profile;
    setReadingAccount(profile.id);
    setUser(profile);
    resetRealtimeConnection();
    return profile;
  }, []);

  const logout = useCallback(async () => {
    const repository = readingRepository();
    await repository?.load();
    if (hasPrivatePendingReading() && !window.confirm('You have unsynced reading changes. Signing out removes them from this device. Sign out anyway?')) return false;
    ++authGeneration.current;
    // Best-effort expiry of CDN viewer-authorization cookies. The signed policy
    // itself remains short-lived even if this request cannot reach Reader Go.
    try { await api.clearCloudFrontCookies(); } catch { /* logout must continue */ }
    await api.logout();
    setReadingAccount(null);
    setUser(null);
    await clearPrivateReading();
    resetRealtimeConnection();
    // Protected encoded bytes are intentionally reusable across token rotation
    // for the same signed-in browser. Explicit sign-out is the privacy boundary:
    // clear them so a later account in this browser cannot inherit that cache.
    await clearProtectedAssetCache();
    return true;
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>
      {readingWarning && <div role="status" className="bg-amber-950 px-4 py-3 text-sm text-amber-100">{readingWarning}</div>}
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
