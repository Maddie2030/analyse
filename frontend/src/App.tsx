import { lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import Navbar from './components/Navbar';
import { runtimeConfig } from './config/runtime';

const Catalog = lazy(() => import('./pages/Catalog'));
const AdvancedSearch = lazy(() => import('./pages/AdvancedSearch'));
const SeriesDetail = lazy(() => import('./pages/SeriesDetail'));
const Reader = lazy(() => import('./pages/Reader'));
const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const Library = lazy(() => import('./pages/Library'));
const Notifications = lazy(() => import('./pages/Notifications'));
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));
const AdminUpload = lazy(() => import('./pages/AdminUpload'));
const AdminStorage = lazy(() => import('./pages/AdminStorage'));
const AdminDatabase = lazy(() => import('./pages/AdminDatabase'));
const AdminCuration = lazy(() => import('./pages/AdminCuration'));
const AdminScraper = lazy(() => import('./pages/AdminScraper'));
const AdminScraperNewSeries = lazy(() => import('./pages/AdminScraperNewSeries'));
const AdminScraperOperations = lazy(() => import('./pages/AdminScraperOperations'));
const Profile = lazy(() => import('./pages/Profile'));

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center"><p className="text-ink-400">Loading...</p></div>;
  if (!user) return <Navigate to="/login" />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center"><p className="text-ink-400">Loading...</p></div>;
  if (!user || user.role !== 'admin') return <Navigate to="/" />;
  return <>{children}</>;
}

function RouteFallback() {
  return <div className="min-h-[40vh] flex items-center justify-center"><p className="text-ink-400">Loading…</p></div>;
}

export default function App() {
  return (
    <div className="min-h-screen min-w-0 max-w-full overflow-x-clip bg-ink-950 pb-16 text-ink-100 md:pb-0">
      <Navbar />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Catalog />} />
          <Route path="/advanced-search" element={<AdvancedSearch />} />
          <Route path="/series/:slug" element={<SeriesDetail />} />
          <Route path="/read/:seriesSlug/:chapterSlug" element={<Reader />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/profile" element={<Protected><Profile /></Protected>} />
          <Route path="/library" element={<Protected><Library /></Protected>} />
          <Route path="/dashboard" element={<Navigate to="/library" replace />} />
          <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
          {runtimeConfig.adminPlane && (<>
            <Route path="/admin" element={<AdminOnly><AdminDashboard /></AdminOnly>} />
            <Route path="/admin/upload" element={<AdminOnly><AdminUpload /></AdminOnly>} />
            <Route path="/admin/storage" element={<AdminOnly><AdminStorage /></AdminOnly>} />
            <Route path="/admin/database" element={<AdminOnly><AdminDatabase /></AdminOnly>} />
            <Route path="/admin/curation" element={<AdminOnly><AdminCuration /></AdminOnly>} />
            <Route path="/admin/scraper" element={<AdminOnly><AdminScraper /></AdminOnly>} />
            <Route path="/admin/scraper/new-series" element={<AdminOnly><AdminScraperNewSeries /></AdminOnly>} />
            <Route path="/admin/scraper/operations" element={<AdminOnly><AdminScraperOperations /></AdminOnly>} />
          </>)}
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </Suspense>
    </div>
  );
}
