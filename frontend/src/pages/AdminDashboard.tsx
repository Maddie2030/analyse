import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Upload, Trash2, ImagePlus, BookOpen, Users, Bell, Layers, Loader2, Database, Star, Tags, Save, HardDriveDownload } from 'lucide-react';
import { api, type Series, type SeriesStatus } from '../api/client';
import { kebabCase } from '../utils/slug';

const SAFE_SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const splitTagNames = (value: string) => Array.from(new Set(
  value.split(',').map((tag) => tag.trim()).filter(Boolean),
));

function CreateSeriesForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({ title: '', slug: '', description: '', status: 'ongoing', tagNames: '' });
  const [slugTouched, setSlugTouched] = useState(false);
  const [thumbnail, setThumbnail] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!SAFE_SLUG_RE.test(form.slug)) { setError('Slug must be lowercase kebab-case.'); return; }
    setSaving(true);
    setError('');
    try {
      const series = await api.createSeries({
        title: form.title,
        slug: form.slug,
        description: form.description,
        status: form.status,
        tag_names: form.tagNames.split(',').map(tag => tag.trim()).filter(Boolean),
      });
      if (thumbnail) {
        // The durable Media job owns the cover DB commit and old-cover cleanup.
        // Do not perform a second Catalog write after it completes.
        await api.uploadSeriesThumbnail(series.slug, thumbnail);
      }
      onCreated();
      setForm({ title: '', slug: '', description: '', status: 'ongoing', tagNames: '' });
      setSlugTouched(false);
      setThumbnail(null);
    } catch (err: any) {
      setError(err?.detail || 'Failed to create series');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="min-w-0 bg-ink-900 border border-ink-800 rounded-xl p-4 sm:p-6 space-y-4 mb-8">
      <h3 className="font-display text-lg font-bold">Create New Series</h3>
      {error && <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-2 rounded-lg text-sm">{error}</div>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm text-ink-300 mb-1">Title</label>
          <input
            type="text"
            value={form.title}
            onChange={(e) => {
              const title = e.target.value;
              setForm((current) => ({
                ...current,
                title,
                slug: slugTouched ? current.slug : kebabCase(title),
              }));
            }}
            required
            className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-sm text-ink-300 mb-1">Slug</label>
          <input
            type="text"
            value={form.slug}
            onChange={(e) => {
              setSlugTouched(true);
              setForm((current) => ({ ...current, slug: e.target.value }));
            }}
            required
            pattern="[a-z0-9-]+"
            className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none"
          />
          <p className="text-xs text-ink-500 mt-1">Title automatically fills this slug in kebab-case until you edit the slug manually.</p>
        </div>
      </div>
      <div>
        <label className="block text-sm text-ink-300 mb-1">Description</label>
        <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none" />
      </div>
      <div>
        <label className="block text-sm text-ink-300 mb-1">Status</label>
        <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none">
          <option value="ongoing">Ongoing</option>
          <option value="completed">Completed</option>
          <option value="hiatus">Hiatus</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>
      <div>
        <label className="block text-sm text-ink-300 mb-1">Tags</label>
        <input
          type="text"
          value={form.tagNames}
          onChange={(e) => setForm({ ...form, tagNames: e.target.value })}
          placeholder="action, drama, horror"
          className="w-full px-4 py-2 bg-ink-950 border border-ink-800 rounded-lg text-ink-100 focus:border-brand-500 focus:outline-none"
        />
        <div className="flex flex-wrap gap-2 mt-2">
          {form.tagNames.split(',').map(tag => tag.trim()).filter(Boolean).map(tag => (
            <span key={tag} className="max-w-full whitespace-normal break-words text-xs px-3 py-1.5 rounded-full bg-brand-600/20 text-brand-300 border border-brand-600/30">
              {tag.toUpperCase()}
            </span>
          ))}
        </div>
        <p className="text-xs text-ink-500 mt-2">Separate multiple tags with commas.</p>
      </div>
      <div>
        <label className="block text-sm text-ink-300 mb-1">Thumbnail (optional)</label>
        <input type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff" onChange={(e) => setThumbnail(e.target.files?.[0] || null)} className="w-full text-sm text-ink-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-brand-600 file:text-white" />
      </div>
      <button type="submit" disabled={saving} className="px-6 py-2 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-lg transition-colors">
        {saving ? 'Creating...' : 'Create Series'}
      </button>
    </form>
  );
}

export default function AdminDashboard() {
  const [series, setSeries] = useState<Series[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [uploadingThumbnailId, setUploadingThumbnailId] = useState<string | null>(null);
  const [updatingStatusId, setUpdatingStatusId] = useState<string | null>(null);
  const [updatingTagsId, setUpdatingTagsId] = useState<string | null>(null);
  const [tagDrafts, setTagDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [deleteNotice, setDeleteNotice] = useState('');
  const [deletingSeriesId, setDeletingSeriesId] = useState<string | null>(null);
  const [chapterCount, setChapterCount] = useState<number | null>(null);
  const [userCount, setUserCount] = useState<number | null>(null);
  const [notificationCount, setNotificationCount] = useState<number | null>(null);
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listSeries('?limit=50');
      setSeries(data);
      setTagDrafts(Object.fromEntries(
        data.map((item) => [item.id, (item.tags || []).map((tag) => tag.name).join(', ')]),
      ));
    } catch {
      setError('Failed to load series');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.getCatalogAdminStats().then((s) => setChapterCount(s.chapter_count)).catch(() => {});
    api.getAuthAdminStats().then((s) => setUserCount(s.user_count)).catch(() => {});
    api.getSocialAdminStats().then((s) => setNotificationCount(s.notification_count)).catch(() => {});
  }, [load]);

  const handleDelete = async (id: string, slug: string) => {
    if (deletingSeriesId) return;
    if (!window.confirm('Delete this series? This cannot be undone.')) return;
    setDeletingSeriesId(id);
    try {
      const result = await api.deleteSeries(id);
      setSeries(prev => prev.filter(s => s.id !== id));
      setDeleteNotice(`Catalog removed. Storage cleanup is ${result.storage_cleanup} (job ${result.job_id}).`);
    } catch {
      setError('Failed to delete series');
    } finally {
      setDeletingSeriesId(null);
    }
  };

  const handleStatusChange = async (s: Series, status: SeriesStatus) => {
    if (status === s.status || updatingStatusId === s.id) return;
    setUpdatingStatusId(s.id);
    setError('');
    try {
      const updated = await api.updateSeries(s.id, { status });
      setSeries((current) => current.map((item) => item.id === s.id ? { ...item, ...updated } : item));
    } catch (err: any) {
      setError(err?.detail || `Failed to change ${s.title} status`);
    } finally {
      setUpdatingStatusId(null);
    }
  };

  const handleTagsSave = async (s: Series) => {
    if (updatingTagsId === s.id) return;
    const tagNames = splitTagNames(tagDrafts[s.id] || '');
    if (tagNames.length > 50) {
      setError('A series can have at most 50 tags.');
      return;
    }
    if (tagNames.some((tag) => Array.from(tag).length > 100)) {
      setError('Each tag must be 100 characters or fewer.');
      return;
    }
    setUpdatingTagsId(s.id);
    setError('');
    try {
      const updated = await api.updateSeries(s.id, { tag_names: tagNames });
      setSeries((current) => current.map((item) => item.id === s.id ? { ...item, ...updated } : item));
      setTagDrafts((current) => ({
        ...current,
        [s.id]: (updated.tags || []).map((tag) => tag.name).join(', '),
      }));
    } catch (err: any) {
      setError(err?.detail || `Failed to update ${s.title} tags`);
    } finally {
      setUpdatingTagsId(null);
    }
  };

  const handleThumbnailChange = async (s: Series, file: File) => {
    setUploadingThumbnailId(s.id);
    try {
      // Completion means the Media service has already committed the new cover
      // path and queued cleanup for the old one. A second Catalog write here
      // creates a false failure boundary and can make a successful upload look
      // broken when Catalog is temporarily unavailable.
      await api.uploadSeriesThumbnail(s.slug, file);
      await load();
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Failed to upload thumbnail');
    } finally {
      setUploadingThumbnailId(null);
    }
  };

  const stats = [
    { label: 'Series', icon: BookOpen, value: series.length },
    { label: 'Chapters', icon: Layers, value: chapterCount ?? '—' },
    { label: 'Users', icon: Users, value: userCount ?? '—' },
    { label: 'Notifications', icon: Bell, value: notificationCount ?? '—' },
  ];

  return (
    <div className="w-full min-w-0 max-w-6xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="font-display text-2xl sm:text-3xl font-bold">Admin Dashboard</h1>
        <div className="flex w-full sm:w-auto flex-wrap gap-2 sm:gap-3">
          <button onClick={() => setShowCreate(!showCreate)} className="flex flex-1 sm:flex-none items-center justify-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium transition-colors">
            <Plus size={18} /> New Series
          </button>
          <Link to="/admin/upload" className="flex flex-1 sm:flex-none items-center justify-center gap-2 px-4 py-2 bg-ink-800 hover:bg-ink-700 text-ink-200 rounded-lg text-sm font-medium transition-colors">
            <Upload size={18} /> Upload
          </Link>
          <Link to="/admin/storage" className="flex flex-1 sm:flex-none items-center justify-center gap-2 px-4 py-2 bg-ink-800 hover:bg-ink-700 text-ink-200 rounded-lg text-sm font-medium transition-colors">
            <Database size={18} /> Storage Exports
          </Link>
          <Link to="/admin/database" className="flex flex-1 sm:flex-none items-center justify-center gap-2 px-4 py-2 bg-ink-800 hover:bg-ink-700 text-ink-200 rounded-lg text-sm font-medium transition-colors">
            <HardDriveDownload size={18} /> Database Protection
          </Link>
          <Link to="/admin/curation" className="flex flex-1 sm:flex-none items-center justify-center gap-2 px-4 py-2 bg-ink-800 hover:bg-ink-700 text-ink-200 rounded-lg text-sm font-medium transition-colors">
            <Star size={18} /> Browse Curation
          </Link>
        </div>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-3 rounded-lg mb-4 text-sm">{error}</div>}
      {deleteNotice && <div className="bg-amber-900/20 border border-amber-700/40 text-amber-200 px-4 py-3 rounded-lg mb-4 text-sm">{deleteNotice}</div>}

      {showCreate && <CreateSeriesForm onCreated={() => { setShowCreate(false); load(); }} />}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {stats.map((stat) => (
          <div key={stat.label} className="bg-ink-900 border border-ink-800 rounded-xl p-4">
            <div className="flex items-center gap-2 text-ink-400 text-sm mb-1"><stat.icon size={16} /> {stat.label}</div>
            <p className="text-2xl font-display font-bold">{stat.value}</p>
          </div>
        ))}
      </div>

      {loading ? (
        <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)}</div>
      ) : (
        <div className="max-w-full bg-ink-900 border border-ink-800 rounded-xl overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-ink-800 text-left text-sm text-ink-400">
                <th className="p-4">Thumbnail</th>
                <th className="p-4">Title</th>
                <th className="p-4">Status</th>
                <th className="p-4 min-w-[18rem]">Tags</th>
                <th className="p-4 hidden lg:table-cell">Updated</th>
                <th className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {series.map((s) => (
                <tr key={s.id} className="border-b border-ink-800 hover:bg-ink-800/50 transition-colors">
                  <td className="p-4">
                    <div className="relative w-12 h-16 rounded overflow-hidden bg-ink-800">
                      {s.cover_image_path ? (
                        <img src={`/images/${s.cover_image_path}`} alt={s.title} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-ink-600 text-xs">{s.title[0]}</div>
                      )}
                    </div>
                  </td>
                  <td className="min-w-0 p-3 sm:p-4">
                    <Link to={`/series/${s.slug}`} className="mreader-break-anywhere text-ink-200 hover:text-brand-400 transition-colors">{s.title}</Link>
                  </td>
                  <td className="p-4">
                    <div className="flex items-center gap-2">
                      <select
                        value={s.status}
                        disabled={updatingStatusId === s.id}
                        onChange={(e) => handleStatusChange(s, e.target.value as SeriesStatus)}
                        aria-label={`Change ${s.title} status`}
                        className={`text-xs px-2 py-1 rounded-lg border border-ink-700 text-white focus:outline-none focus:border-brand-500 disabled:opacity-60 ${
                          s.status === 'ongoing'
                            ? 'bg-green-700/80'
                            : s.status === 'completed'
                              ? 'bg-blue-700/80'
                              : s.status === 'cancelled'
                                ? 'bg-red-700/80'
                                : 'bg-yellow-700/80'
                        }`}
                      >
                        <option value="ongoing">Ongoing</option>
                        <option value="hiatus">Hiatus</option>
                        <option value="completed">Completed</option>
                        <option value="cancelled">Cancelled</option>
                      </select>
                      {updatingStatusId === s.id && <Loader2 size={14} className="animate-spin text-ink-400" />}
                    </div>
                  </td>
                  <td className="p-4 min-w-[18rem]">
                    <div className="flex items-center gap-2">
                      <div className="relative min-w-0 flex-1">
                        <Tags size={14} className="pointer-events-none absolute left-2.5 top-2.5 text-ink-500" />
                        <input
                          type="text"
                          value={tagDrafts[s.id] ?? (s.tags || []).map((tag) => tag.name).join(', ')}
                          onChange={(e) => setTagDrafts((current) => ({ ...current, [s.id]: e.target.value }))}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              void handleTagsSave(s);
                            }
                          }}
                          disabled={updatingTagsId === s.id}
                          aria-label={`Edit ${s.title} tags`}
                          placeholder="action, fantasy, revenge"
                          className="w-full rounded-lg border border-ink-700 bg-ink-950 py-2 pl-8 pr-2 text-xs text-ink-200 focus:border-brand-500 focus:outline-none disabled:opacity-60"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleTagsSave(s)}
                        disabled={updatingTagsId === s.id}
                        title="Save tags"
                        aria-label={`Save ${s.title} tags`}
                        className="rounded-lg border border-ink-700 bg-ink-800 p-2 text-ink-300 transition hover:border-brand-500 hover:text-brand-300 disabled:opacity-50"
                      >
                        {updatingTagsId === s.id ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                      </button>
                    </div>
                    <p className="mt-1 text-[11px] text-ink-500">Comma-separated. New names are created automatically.</p>
                  </td>
                  <td className="p-4 hidden lg:table-cell text-ink-400 text-sm">{new Date(s.updated_at).toLocaleDateString()}</td>
                  <td className="p-4">
                    <div className="flex items-center justify-end gap-2">
                      <input
                        ref={(el) => { fileInputRefs.current[s.id] = el; }}
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff"
                        className="hidden"
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleThumbnailChange(s, f); }}
                      />
                      <button onClick={() => fileInputRefs.current[s.id]?.click()} disabled={uploadingThumbnailId === s.id} className="p-2 text-ink-400 hover:text-brand-400 transition-colors disabled:opacity-50">
                        {uploadingThumbnailId === s.id ? <Loader2 size={18} className="animate-spin" /> : <ImagePlus size={18} />}
                      </button>
                      <button onClick={() => handleDelete(s.id, s.slug)} disabled={deletingSeriesId === s.id} className="p-2 text-ink-400 hover:text-red-400 disabled:opacity-50 transition-colors">
                        {deletingSeriesId === s.id ? <Loader2 size={18} className="animate-spin" /> : <Trash2 size={18} />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
