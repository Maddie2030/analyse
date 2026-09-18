import { useEffect, useState, type ElementType } from 'react';
import { Link, NavLink as RRNavLink, useLocation, useNavigate } from 'react-router-dom';
import { Activity, Bell, BookOpen, Compass, Library, LogIn, LogOut, Menu, Search, Shield, ShieldCheck, Upload, User, Star, HardDrive } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useNotifications } from '../hooks/useNotifications';
import { avatarSrc } from '../utils/avatars';
import { runtimeConfig } from '../config/runtime';

function NavLink({ to, icon: Icon, label, badge }: { to: string; icon: ElementType; label: string; badge?: number }) {
  return (
    <RRNavLink to={to} className={({ isActive }) => `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
      isActive ? 'bg-brand-600/10 text-brand-400' : 'text-ink-300 hover:bg-ink-800 hover:text-ink-100'
    }`}>
      <Icon size={18} />
      <span>{label}</span>
      {badge !== undefined && badge > 0 && <span className="ml-1 rounded-full bg-brand-600 px-1.5 py-0.5 text-xs font-bold text-white">{badge > 99 ? '99+' : badge}</span>}
    </RRNavLink>
  );
}

function MobileMenuLink({ to, icon: Icon, label, onClick }: { to: string; icon: ElementType; label: string; onClick: () => void }) {
  return (
    <Link to={to} onClick={onClick} className="flex items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium text-ink-300 transition-colors hover:bg-ink-800 hover:text-ink-100">
      <Icon size={18} /> {label}
    </Link>
  );
}

function BottomLink({ to, icon: Icon, label, badge }: { to: string; icon: ElementType; label: string; badge?: number }) {
  return (
    <RRNavLink to={to} className={({ isActive }) => `relative flex min-w-[64px] flex-col items-center justify-center gap-1 px-2 py-2 text-[11px] font-medium transition-colors ${isActive ? 'text-brand-400' : 'text-ink-400'}`}>
      <span className="relative">
        <Icon size={20} />
        {badge !== undefined && badge > 0 && <span className="absolute -right-3 -top-2 min-w-4 rounded-full bg-brand-600 px-1 text-center text-[9px] font-bold leading-4 text-white">{badge > 99 ? '99+' : badge}</span>}
      </span>
      {label}
    </RRNavLink>
  );
}

export default function Navbar() {
  const { user, logout } = useAuth();
  const { unreadCount } = useNotifications();
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const readerRoute = location.pathname.startsWith('/read/');

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        navigate('/advanced-search');
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [navigate]);

  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

  const handleLogout = async () => {
    if (!await logout()) return;
    navigate('/');
  };

  return (
    <>
      <nav className="sticky top-0 z-50 flex h-14 min-w-0 max-w-full items-center border-b border-ink-800 bg-ink-900/95 px-3 backdrop-blur sm:px-4">
        <Link to="/" aria-label="Browse series" title="Browse series" className="mr-3 flex shrink-0 items-center gap-2 text-ink-100 transition-colors hover:text-brand-400 sm:mr-6">
          <BookOpen className="text-brand-400" size={24} />
          <span className="hidden font-display text-lg font-bold sm:inline">ManhwaReader</span>
        </Link>

        <div className="hidden items-center gap-1 md:flex">
          <NavLink to="/" icon={Compass} label="Browse" />
          <NavLink to="/advanced-search" icon={Search} label="Search" />
          {user && <NavLink to="/library" icon={Library} label="Library" />}
          {user && <NavLink to="/notifications" icon={Bell} label="Alerts" badge={unreadCount} />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin" icon={Shield} label="Admin" />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin/upload" icon={Upload} label="Upload" />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin/scraper" icon={Upload} label="Scraper" />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin/scraper/operations" icon={Activity} label="Scrape Ops" />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin/curation" icon={Star} label="Curation" />}
          {runtimeConfig.adminPlane && user?.role === 'admin' && <NavLink to="/admin/database" icon={HardDrive} label="DB Protect" />}
        </div>

        <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-2">
          <button type="button" onClick={() => navigate('/advanced-search')} className="hidden items-center gap-2 rounded-lg border border-ink-800 bg-ink-950/60 px-3 py-2 text-xs text-ink-400 transition hover:border-ink-700 hover:text-ink-200 lg:flex" title="Search (Ctrl/⌘ + K)">
            <Search size={15} /> Search <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-[10px]">Ctrl K</kbd>
          </button>
          {user ? (
            <>
              <Link to="/profile" className="relative flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-ink-300 transition-colors hover:bg-ink-800 hover:text-ink-100" title="Profile & settings">
                <span className="relative">
                  <img src={avatarSrc(user.avatar_key)} alt="" className="h-7 w-7 rounded-full border border-ink-700 bg-ink-950 object-cover" />
                  {user.role === 'admin' && <ShieldCheck size={12} className="absolute -right-1.5 -bottom-1.5 rounded-full bg-ink-900 text-amber-300" aria-label="Administrator" />}
                </span>
                <span className="hidden sm:inline">{user.username}</span>
              </Link>
              <button type="button" onClick={handleLogout} className="hidden items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-300 transition-colors hover:bg-ink-800 hover:text-brand-400 sm:flex">
                <LogOut size={18} /><span className="hidden lg:inline">Logout</span>
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="hidden rounded-lg px-3 py-2 text-sm font-medium text-ink-300 transition-colors hover:text-ink-100 sm:block">Login</Link>
              <Link to="/register" className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500">Sign up</Link>
            </>
          )}
          <button type="button" onClick={() => setMenuOpen((current) => !current)} className="rounded-lg p-2 text-ink-300 hover:bg-ink-800 md:hidden" aria-label="Open menu"><Menu size={20} /></button>
        </div>

        {menuOpen && (
          <div className="absolute left-0 right-0 top-14 flex flex-col gap-1 border-b border-ink-800 bg-ink-900 p-3 md:hidden animate-fade-in">
            {user && (
              <Link to="/profile" onClick={() => setMenuOpen(false)} className="flex items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium text-ink-300 transition-colors hover:bg-ink-800 hover:text-ink-100">
                <span className="relative">
                  <img src={avatarSrc(user.avatar_key)} alt="" className="h-8 w-8 rounded-full border border-ink-700 bg-ink-950 object-cover" />
                  {user.role === 'admin' && <ShieldCheck size={12} className="absolute -right-1.5 -bottom-1.5 rounded-full bg-ink-900 text-amber-300" aria-label="Administrator" />}
                </span>
                Profile & settings
              </Link>
            )}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin" icon={Shield} label="Admin dashboard" onClick={() => setMenuOpen(false)} />}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin/upload" icon={Upload} label="Upload chapter" onClick={() => setMenuOpen(false)} />}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin/scraper" icon={Upload} label="Scraper" onClick={() => setMenuOpen(false)} />}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin/scraper/operations" icon={Activity} label="Scrape operations" onClick={() => setMenuOpen(false)} />}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin/curation" icon={Star} label="Browse curation" onClick={() => setMenuOpen(false)} />}
            {runtimeConfig.adminPlane && user?.role === 'admin' && <MobileMenuLink to="/admin/database" icon={HardDrive} label="Database protection" onClick={() => setMenuOpen(false)} />}
            {user ? (
              <button type="button" onClick={handleLogout} className="flex items-center gap-3 rounded-lg px-4 py-3 text-left text-sm font-medium text-ink-300 transition-colors hover:bg-ink-800 hover:text-brand-400"><LogOut size={18} /> Logout</button>
            ) : (
              <MobileMenuLink to="/login" icon={LogIn} label="Sign in" onClick={() => setMenuOpen(false)} />
            )}
          </div>
        )}
      </nav>

      {!readerRoute && (
        <nav className="fixed inset-x-0 bottom-0 z-50 flex h-16 items-center justify-around border-t border-ink-800 bg-ink-900/97 px-2 backdrop-blur md:hidden" aria-label="Primary mobile navigation">
          <BottomLink to="/" icon={Compass} label="Browse" />
          <BottomLink to="/advanced-search" icon={Search} label="Search" />
          {user ? <BottomLink to="/library" icon={Library} label="Library" /> : <BottomLink to="/login" icon={LogIn} label="Sign in" />}
          {user && <BottomLink to="/notifications" icon={Bell} label="Alerts" badge={unreadCount} />}
        </nav>
      )}
    </>
  );
}
