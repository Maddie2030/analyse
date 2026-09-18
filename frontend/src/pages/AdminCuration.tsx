import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Loader2, Megaphone, Pencil, Plus, Save, Star, Trash2, X } from 'lucide-react';
import {
  api,
  type Announcement,
  type AnnouncementTone,
  type AnnouncementUpsert,
  type EditorPick,
  type EditorPickUpsert,
  type Series,
} from '../api/client';
import SearchableSeriesPicker, { type SeriesPickerOption } from '../components/SearchableSeriesPicker';

type PickForm = {
  id: string | null;
  series: SeriesPickerOption | null;
  label: string;
  note: string;
  position: number;
  isActive: boolean;
  startsAt: string;
  endsAt: string;
};

type AnnouncementForm = {
  id: string | null;
  title: string;
  body: string;
  linkUrl: string;
  linkLabel: string;
  tone: AnnouncementTone;
  dismissible: boolean;
  position: number;
  isActive: boolean;
  startsAt: string;
  endsAt: string;
};

const emptyPick = (): PickForm => ({ id: null, series: null, label: '', note: '', position: 0, isActive: true, startsAt: '', endsAt: '' });
const emptyAnnouncement = (): AnnouncementForm => ({ id: null, title: '', body: '', linkUrl: '', linkLabel: '', tone: 'info', dismissible: true, position: 0, isActive: true, startsAt: '', endsAt: '' });

function toLocalInput(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toISO(value: string) {
  return value ? new Date(value).toISOString() : null;
}

function scheduleLabel(active: boolean, startsAt: string | null, endsAt: string | null) {
  if (!active) return 'Inactive';
  const now = Date.now();
  if (startsAt && Date.parse(startsAt) > now) return 'Scheduled';
  if (endsAt && Date.parse(endsAt) <= now) return 'Expired';
  return 'Live';
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="mb-1 block text-xs font-semibold uppercase tracking-wider text-ink-500">{children}</label>;
}

export default function AdminCuration() {
  const [picks, setPicks] = useState<EditorPick[]>([]);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [pickForm, setPickForm] = useState<PickForm>(emptyPick());
  const [announcementForm, setAnnouncementForm] = useState<AnnouncementForm>(emptyAnnouncement());
  const [seriesQuery, setSeriesQuery] = useState('');
  const [seriesOptions, setSeriesOptions] = useState<SeriesPickerOption[]>([]);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<'pick' | 'announcement' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAdminCuration();
      setPicks(data.editor_picks || []);
      setAnnouncements(data.announcements || []);
      setError('');
    } catch {
      setError('Failed to load curation settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const query = seriesQuery.trim();
    if (!query) {
      setSeriesOptions([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSeriesLoading(true);
      try {
        const rows = await api.listSeries(`?search=${encodeURIComponent(query)}&sort=relevance&limit=8`);
        if (!cancelled) setSeriesOptions(rows.map((row: Series) => ({ id: row.id, title: row.title, slug: row.slug, subtitle: row.status })));
      } catch {
        if (!cancelled) setSeriesOptions([]);
      } finally {
        if (!cancelled) setSeriesLoading(false);
      }
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [seriesQuery]);

  const usedSeries = useMemo(() => new Set(picks.filter((item) => item.id !== pickForm.id).map((item) => item.series.id)), [picks, pickForm.id]);
  const availableSeriesOptions = seriesOptions.filter((option) => !usedSeries.has(option.id) || option.id === pickForm.series?.id);

  const editPick = (item: EditorPick) => {
    const selected = { id: item.series.id, title: item.series.title, slug: item.series.slug, subtitle: item.series.status };
    setPickForm({
      id: item.id, series: selected, label: item.label || '', note: item.note || '', position: item.position,
      isActive: item.is_active, startsAt: toLocalInput(item.starts_at), endsAt: toLocalInput(item.ends_at),
    });
    setSeriesQuery(item.series.title);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const submitPick = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!pickForm.series) { setError('Choose a series for the Editor Pick.'); return; }
    if (pickForm.startsAt && pickForm.endsAt && Date.parse(pickForm.endsAt) <= Date.parse(pickForm.startsAt)) { setError('Editor Pick end time must be after its start time.'); return; }
    const body: EditorPickUpsert = {
      series_id: pickForm.series.id,
      label: pickForm.label.trim() || null,
      note: pickForm.note.trim() || null,
      position: Math.max(0, Number(pickForm.position) || 0),
      is_active: pickForm.isActive,
      starts_at: toISO(pickForm.startsAt),
      ends_at: toISO(pickForm.endsAt),
    };
    setSaving('pick'); setError(''); setNotice('');
    try {
      if (pickForm.id) await api.updateEditorPick(pickForm.id, body); else await api.createEditorPick(body);
      setPickForm(emptyPick()); setSeriesQuery(''); setSeriesOptions([]);
      setNotice('Editor Picks updated.');
      await load();
    } catch (err: any) {
      setError(err?.detail || 'Failed to save Editor Pick.');
    } finally { setSaving(null); }
  };

  const removePick = async (item: EditorPick) => {
    if (!window.confirm(`Remove ${item.series.title} from Editor's Picks?`)) return;
    try { await api.deleteEditorPick(item.id); await load(); } catch { setError('Failed to remove Editor Pick.'); }
  };

  const editAnnouncement = (item: Announcement) => {
    setAnnouncementForm({
      id: item.id, title: item.title, body: item.body, linkUrl: item.link_url || '', linkLabel: item.link_label || '',
      tone: item.tone, dismissible: item.dismissible, position: item.position, isActive: item.is_active,
      startsAt: toLocalInput(item.starts_at), endsAt: toLocalInput(item.ends_at),
    });
  };

  const submitAnnouncement = async (event: React.FormEvent) => {
    event.preventDefault();
    if (announcementForm.startsAt && announcementForm.endsAt && Date.parse(announcementForm.endsAt) <= Date.parse(announcementForm.startsAt)) { setError('Announcement end time must be after its start time.'); return; }
    const body: AnnouncementUpsert = {
      title: announcementForm.title.trim(), body: announcementForm.body.trim(),
      link_url: announcementForm.linkUrl.trim() || null, link_label: announcementForm.linkLabel.trim() || null,
      tone: announcementForm.tone, dismissible: announcementForm.dismissible,
      position: Math.max(0, Number(announcementForm.position) || 0), is_active: announcementForm.isActive,
      starts_at: toISO(announcementForm.startsAt), ends_at: toISO(announcementForm.endsAt),
    };
    if (!body.title || !body.body) { setError('Announcement title and body are required.'); return; }
    setSaving('announcement'); setError(''); setNotice('');
    try {
      if (announcementForm.id) await api.updateAnnouncement(announcementForm.id, body); else await api.createAnnouncement(body);
      setAnnouncementForm(emptyAnnouncement()); setNotice('Announcements updated.'); await load();
    } catch (err: any) { setError(err?.detail || 'Failed to save announcement.'); }
    finally { setSaving(null); }
  };

  const removeAnnouncement = async (item: Announcement) => {
    if (!window.confirm(`Delete announcement “${item.title}”?`)) return;
    try { await api.deleteAnnouncement(item.id); await load(); } catch { setError('Failed to delete announcement.'); }
  };

  return (
    <div className="mx-auto w-full min-w-0 max-w-6xl px-3 py-6 sm:px-4 sm:py-8 animate-fade-in">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/admin" className="mb-2 inline-flex items-center gap-1 text-xs text-ink-500 hover:text-brand-400"><ArrowLeft size={14} /> Admin dashboard</Link>
          <h1 className="font-display text-2xl font-bold sm:text-3xl">Browse Curation</h1>
          <p className="mt-1 text-sm text-ink-500">Schedule Editor's Picks and public announcements without deploying frontend code.</p>
        </div>
      </div>

      {error && <div className="mb-4 rounded-xl border border-red-800/60 bg-red-950/30 px-4 py-3 text-sm text-red-300">{error}</div>}
      {notice && <div className="mb-4 rounded-xl border border-green-800/60 bg-green-950/20 px-4 py-3 text-sm text-green-300">{notice}</div>}

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="rounded-2xl border border-ink-800 bg-ink-900 p-4 sm:p-5">
          <div className="mb-4 flex items-center gap-2"><Star size={20} className="text-amber-400" /><h2 className="font-display text-xl font-bold">Editor's Picks</h2></div>
          <form onSubmit={submitPick} className="space-y-4">
            <SearchableSeriesPicker label="Series" query={seriesQuery} onQueryChange={(value) => { setSeriesQuery(value); if (pickForm.series && value !== pickForm.series.title) setPickForm((current) => ({ ...current, series: null })); }} options={availableSeriesOptions} selected={pickForm.series} onSelect={(series) => setPickForm((current) => ({ ...current, series }))} loading={seriesLoading} />
            <div className="grid gap-3 sm:grid-cols-2">
              <div><FieldLabel>Badge label</FieldLabel><input value={pickForm.label} maxLength={80} onChange={(e) => setPickForm((c) => ({ ...c, label: e.target.value }))} placeholder="Editor's choice" className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5 outline-none focus:border-brand-500" /></div>
              <div><FieldLabel>Position</FieldLabel><input type="number" min={0} value={pickForm.position} onChange={(e) => setPickForm((c) => ({ ...c, position: Number(e.target.value) }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5 outline-none focus:border-brand-500" /></div>
            </div>
            <div><FieldLabel>Recommendation note</FieldLabel><textarea value={pickForm.note} maxLength={280} rows={3} onChange={(e) => setPickForm((c) => ({ ...c, note: e.target.value }))} className="w-full resize-y rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5 outline-none focus:border-brand-500" /></div>
            <div className="grid gap-3 sm:grid-cols-2"><div><FieldLabel>Starts</FieldLabel><input type="datetime-local" value={pickForm.startsAt} onChange={(e) => setPickForm((c) => ({ ...c, startsAt: e.target.value }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div><div><FieldLabel>Ends</FieldLabel><input type="datetime-local" value={pickForm.endsAt} onChange={(e) => setPickForm((c) => ({ ...c, endsAt: e.target.value }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div></div>
            <label className="flex items-center gap-2 text-sm text-ink-300"><input type="checkbox" checked={pickForm.isActive} onChange={(e) => setPickForm((c) => ({ ...c, isActive: e.target.checked }))} /> Active</label>
            <div className="flex gap-2"><button disabled={saving === 'pick'} className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving === 'pick' ? <Loader2 size={16} className="animate-spin" /> : pickForm.id ? <Save size={16} /> : <Plus size={16} />}{pickForm.id ? 'Save Pick' : 'Add Pick'}</button>{pickForm.id && <button type="button" onClick={() => { setPickForm(emptyPick()); setSeriesQuery(''); }} className="inline-flex items-center gap-2 rounded-xl bg-ink-800 px-4 py-2.5 text-sm"><X size={16} /> Cancel</button>}</div>
          </form>

          <div className="mt-6 space-y-2 border-t border-ink-800 pt-5">
            {loading ? <div className="skeleton h-20 rounded-xl" /> : picks.length === 0 ? <p className="text-sm text-ink-500">No Editor Picks yet.</p> : picks.map((item) => <div key={item.id} className="flex min-w-0 items-center gap-3 rounded-xl border border-ink-800 bg-ink-950/60 p-3"><div className="min-w-0 flex-1"><p className="truncate font-medium">{item.series.title}</p><p className="mt-1 text-xs text-ink-500">#{item.position} · {scheduleLabel(item.is_active, item.starts_at, item.ends_at)}{item.label ? ` · ${item.label}` : ''}</p></div><button type="button" onClick={() => editPick(item)} className="rounded-lg p-2 text-ink-400 hover:bg-ink-800 hover:text-brand-400"><Pencil size={16} /></button><button type="button" onClick={() => removePick(item)} className="rounded-lg p-2 text-ink-400 hover:bg-red-950/40 hover:text-red-400"><Trash2 size={16} /></button></div>)}
          </div>
        </section>

        <section className="rounded-2xl border border-ink-800 bg-ink-900 p-4 sm:p-5">
          <div className="mb-4 flex items-center gap-2"><Megaphone size={20} className="text-brand-400" /><h2 className="font-display text-xl font-bold">Announcements</h2></div>
          <form onSubmit={submitAnnouncement} className="space-y-4">
            <div><FieldLabel>Title</FieldLabel><input value={announcementForm.title} maxLength={120} onChange={(e) => setAnnouncementForm((c) => ({ ...c, title: e.target.value }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5 outline-none focus:border-brand-500" /></div>
            <div><FieldLabel>Message</FieldLabel><textarea value={announcementForm.body} maxLength={1000} rows={4} onChange={(e) => setAnnouncementForm((c) => ({ ...c, body: e.target.value }))} className="w-full resize-y rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5 outline-none focus:border-brand-500" /></div>
            <div className="grid gap-3 sm:grid-cols-2"><div><FieldLabel>Link URL</FieldLabel><input value={announcementForm.linkUrl} onChange={(e) => setAnnouncementForm((c) => ({ ...c, linkUrl: e.target.value }))} placeholder="/series/... or https://..." className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div><div><FieldLabel>Link label</FieldLabel><input value={announcementForm.linkLabel} maxLength={80} onChange={(e) => setAnnouncementForm((c) => ({ ...c, linkLabel: e.target.value }))} placeholder="Read more" className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div></div>
            <div className="grid gap-3 sm:grid-cols-2"><div><FieldLabel>Tone</FieldLabel><select value={announcementForm.tone} onChange={(e) => setAnnouncementForm((c) => ({ ...c, tone: e.target.value as AnnouncementTone }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5"><option value="info">Info</option><option value="success">Success</option><option value="warning">Warning</option><option value="critical">Critical</option></select></div><div><FieldLabel>Position</FieldLabel><input type="number" min={0} value={announcementForm.position} onChange={(e) => setAnnouncementForm((c) => ({ ...c, position: Number(e.target.value) }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div></div>
            <div className="grid gap-3 sm:grid-cols-2"><div><FieldLabel>Starts</FieldLabel><input type="datetime-local" value={announcementForm.startsAt} onChange={(e) => setAnnouncementForm((c) => ({ ...c, startsAt: e.target.value }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div><div><FieldLabel>Ends</FieldLabel><input type="datetime-local" value={announcementForm.endsAt} onChange={(e) => setAnnouncementForm((c) => ({ ...c, endsAt: e.target.value }))} className="w-full rounded-xl border border-ink-800 bg-ink-950 px-3 py-2.5" /></div></div>
            <div className="flex flex-wrap gap-4"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={announcementForm.isActive} onChange={(e) => setAnnouncementForm((c) => ({ ...c, isActive: e.target.checked }))} /> Active</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={announcementForm.dismissible} onChange={(e) => setAnnouncementForm((c) => ({ ...c, dismissible: e.target.checked }))} /> Dismissible</label></div>
            <div className="flex gap-2"><button disabled={saving === 'announcement'} className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving === 'announcement' ? <Loader2 size={16} className="animate-spin" /> : announcementForm.id ? <Save size={16} /> : <Plus size={16} />}{announcementForm.id ? 'Save Announcement' : 'Add Announcement'}</button>{announcementForm.id && <button type="button" onClick={() => setAnnouncementForm(emptyAnnouncement())} className="inline-flex items-center gap-2 rounded-xl bg-ink-800 px-4 py-2.5 text-sm"><X size={16} /> Cancel</button>}</div>
          </form>

          <div className="mt-6 space-y-2 border-t border-ink-800 pt-5">
            {loading ? <div className="skeleton h-20 rounded-xl" /> : announcements.length === 0 ? <p className="text-sm text-ink-500">No announcements yet.</p> : announcements.map((item) => <div key={item.id} className="flex min-w-0 items-start gap-3 rounded-xl border border-ink-800 bg-ink-950/60 p-3"><div className="min-w-0 flex-1"><p className="truncate font-medium">{item.title}</p><p className="mt-1 line-clamp-2 text-xs text-ink-500">#{item.position} · {scheduleLabel(item.is_active, item.starts_at, item.ends_at)} · {item.tone} · {item.body}</p></div><button type="button" onClick={() => editAnnouncement(item)} className="rounded-lg p-2 text-ink-400 hover:bg-ink-800 hover:text-brand-400"><Pencil size={16} /></button><button type="button" onClick={() => removeAnnouncement(item)} className="rounded-lg p-2 text-ink-400 hover:bg-red-950/40 hover:text-red-400"><Trash2 size={16} /></button></div>)}
          </div>
        </section>
      </div>
    </div>
  );
}
