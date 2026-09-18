import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link } from 'react-router-dom';
import { FileArchive, Loader2, Upload } from 'lucide-react';
import { api, type Series } from '../api/client';
import { kebabCase } from '../utils/slug';
import SearchableSeriesPicker, {
  type SeriesPickerOption,
} from '../components/SearchableSeriesPicker';

export default function AdminUpload() {
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [seriesSearch, setSeriesSearch] = useState('');
  const [seriesLoading, setSeriesLoading] = useState(false);

  const [chapterSlug, setChapterSlug] = useState('');
  const [chapterNumber, setChapterNumber] = useState(1);
  const [chapterTitle, setChapterTitle] = useState('');
  const [chapterSlugTouched, setChapterSlugTouched] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [firstImage, setFirstImage] = useState<File | null>(null);
  const [lastImage, setLastImage] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{
    page_count: number;
    total_size_bytes: number;
  } | null>(null);
  const [error, setError] = useState('');
  const seriesRequestRef = useRef(0);

  const loadSeries = useCallback(async (search: string) => {
    const requestId = ++seriesRequestRef.current;
    setSeriesLoading(true);

    try {
      const params = new URLSearchParams();
      params.set('limit', '50');

      if (search.trim()) {
        params.set('search', search.trim());
      }

      const data = await api.listSeries(`?${params.toString()}`);
      if (requestId !== seriesRequestRef.current) return;
      setSeriesList(data);
      setError('');
    } catch {
      if (requestId !== seriesRequestRef.current) return;
      setError('Failed to search series. Showing the last successful matches.');
    } finally {
      if (requestId === seriesRequestRef.current) setSeriesLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSeries(seriesSearch);
    }, 250);

    return () => window.clearTimeout(timer);
  }, [loadSeries, seriesSearch]);

  const pickerOptions = useMemo<SeriesPickerOption[]>(
    () =>
      seriesList.map((item) => ({
        id: item.id,
        title: item.title,
        slug: item.slug,
        subtitle: item.status,
      })),
    [seriesList]
  );

  const selectedPickerOption = useMemo<SeriesPickerOption | null>(
    () =>
      selectedSeries
        ? {
            id: selectedSeries.id,
            title: selectedSeries.title,
            slug: selectedSeries.slug,
            subtitle: selectedSeries.status,
          }
        : null,
    [selectedSeries]
  );

  const selectSeries = (option: SeriesPickerOption | null) => {
    if (!option) {
      setSelectedSeries(null);
      return;
    }

    const item = seriesList.find((series) => series.id === option.id);
    if (item) setSelectedSeries(item);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (!selectedSeries || !chapterSlug || !file) {
      setError('Series, slug, and file are required.');
      return;
    }

    setUploading(true);
    setError('');
    setResult(null);

    try {
      const response = await api.uploadChapter(
        selectedSeries.slug,
        chapterSlug,
        file,
        parseFloat(String(chapterNumber)) || 1,
        chapterTitle || null,
        firstImage,
        lastImage
      );

      setResult({
        page_count: response.page_count,
        total_size_bytes: response.total_size_bytes,
      });
      setChapterNumber(1);
      setChapterTitle('');
      setChapterSlug('');
      setChapterSlugTouched(false);
      setFile(null);
      setFirstImage(null);
      setLastImage(null);
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="w-full min-w-0 max-w-2xl mx-auto px-3 sm:px-4 py-6 sm:py-8 animate-fade-in">
      <div className="flex items-center gap-3 mb-6">
        <Link
          to="/admin"
          className="text-ink-400 hover:text-ink-100 text-sm"
        >
          Back to Admin
        </Link>
      </div>

      <h1 className="font-display text-2xl sm:text-3xl font-bold mb-6">
        Upload Chapter
      </h1>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 text-red-300 px-4 py-3 rounded-lg mb-4 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-green-900/30 border border-green-700/50 text-green-300 px-4 py-3 rounded-lg mb-4 text-sm">
          Upload successful! {result.page_count} pages,{' '}
          {(result.total_size_bytes / 1024 / 1024).toFixed(1)} MB
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <SearchableSeriesPicker
          query={seriesSearch}
          onQueryChange={setSeriesSearch}
          options={pickerOptions}
          selected={selectedPickerOption}
          onSelect={selectSeries}
          loading={seriesLoading}
          placeholder="Search series by title or slug…"
          emptyText="No matching series. Try another title or slug."
        />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-ink-300 mb-1">
              Chapter Number
            </label>
            <input
              type="number"
              step="0.01"
              value={chapterNumber}
              onChange={(event) =>
                setChapterNumber(parseFloat(event.target.value))
              }
              required
              className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm text-ink-300 mb-1">
              Chapter Slug
            </label>
            <input
              type="text"
              value={chapterSlug}
              onChange={(event) => {
                setChapterSlugTouched(true);
                setChapterSlug(event.target.value);
              }}
              required
              pattern="[a-z0-9\-]+"
              className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm text-ink-300 mb-1">
            Chapter Title (optional)
          </label>
          <input
            type="text"
            value={chapterTitle}
            onChange={(event) => {
              const value = event.target.value;
              setChapterTitle(value);
              if (!chapterSlugTouched || !chapterSlug) {
                setChapterSlug(kebabCase(value));
              }
            }}
            placeholder="Example: The Hero Returns"
            className="w-full px-4 py-3 bg-ink-900 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
          />
          <p className="text-xs text-ink-500 mt-1">Typing a title automatically fills the chapter slug in kebab-case until you edit the slug manually.</p>
        </div>

        <div>
          <label className="block text-sm text-ink-300 mb-1">
            ZIP/CBZ/PDF
          </label>

          <div className="min-w-0 border-2 border-dashed border-ink-700 rounded-xl p-4 sm:p-8 text-center hover:border-brand-500 transition-colors">
            <FileArchive size={32} className="mx-auto text-ink-500 mb-2" />

            <input
              type="file"
              accept=".zip,.cbz,.pdf,application/zip,application/x-zip-compressed,application/x-cbz,application/pdf"
              onChange={(event) =>
                setFile(event.target.files?.[0] || null)
              }
              className="w-full max-w-full text-sm text-ink-400 file:mr-2 sm:file:mr-3 file:py-2 file:px-3 sm:file:px-4 file:rounded-lg file:border-0 file:bg-brand-600 file:text-white"
            />

            {file && (
              <p className="mreader-break-anywhere text-ink-300 text-sm mt-2">{file.name}</p>
            )}
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-ink-300 mb-1">First page image (optional)</label>
            <input
              type="file"
              accept="image/*,.avif,.heic,.tif,.tiff"
              onChange={(event) => setFirstImage(event.target.files?.[0] || null)}
              className="w-full text-sm text-ink-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-ink-800 file:text-ink-200"
            />
            <p className="text-xs text-ink-500 mt-1">Inserted before the archive's first page and processed through the normal WebP pipeline.</p>
          </div>
          <div>
            <label className="block text-sm text-ink-300 mb-1">Last page image (optional)</label>
            <input
              type="file"
              accept="image/*,.avif,.heic,.tif,.tiff"
              onChange={(event) => setLastImage(event.target.files?.[0] || null)}
              className="w-full text-sm text-ink-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-ink-800 file:text-ink-200"
            />
            <p className="text-xs text-ink-500 mt-1">Appended after the archive's final page for this chapter only.</p>
          </div>
        </div>

        <button
          type="submit"
          disabled={uploading || !selectedSeries}
          className="w-full py-3 bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
        >
          {uploading ? (
            <>
              <Loader2 className="animate-spin" size={18} />
              Uploading...
            </>
          ) : (
            <>
              <Upload size={18} />
              Upload & Publish
            </>
          )}
        </button>
      </form>
    </div>
  );
}
