import {
  CheckCircle2,
  ChevronDown,
  Loader2,
  Search,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';

export interface SeriesPickerOption {
  id: string;
  title: string;
  slug: string;
  subtitle?: string;
}

interface SearchableSeriesPickerProps {
  label?: string;
  query: string;
  onQueryChange: (value: string) => void;
  options: SeriesPickerOption[];
  selected: SeriesPickerOption | null;
  onSelect: (option: SeriesPickerOption | null) => void;
  loading?: boolean;
  placeholder?: string;
  showSelectFallback?: boolean;
  emptyText?: string;
}

export default function SearchableSeriesPicker({
  label = 'Series',
  query,
  onQueryChange,
  options,
  selected,
  onSelect,
  loading = false,
  placeholder = 'Search title or slug…',
  showSelectFallback = false,
  emptyText = 'No matching series found.',
}: SearchableSeriesPickerProps) {
  const [focused, setFocused] = useState(false);

  const selectOptions = useMemo(() => {
    if (!selected || options.some((option) => option.id === selected.id)) {
      return options;
    }

    return [selected, ...options];
  }, [options, selected]);

  const choose = (option: SeriesPickerOption) => {
    onSelect(option);
    onQueryChange(option.title);
    setFocused(false);
  };

  const clear = () => {
    onSelect(null);
    onQueryChange('');
    setFocused(true);
  };

  return (
    <div>
      <label className="block text-sm text-ink-300 mb-1">{label}</label>

      <div className="relative">
        <Search
          size={17}
          className="absolute left-3 top-3.5 text-ink-500 pointer-events-none"
        />

        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            window.setTimeout(() => setFocused(false), 140);
          }}
          placeholder={placeholder}
          autoComplete="off"
          className="w-full pl-10 pr-12 py-3 bg-ink-950 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none transition-colors"
        />

        {loading ? (
          <Loader2
            size={17}
            className="absolute right-4 top-3.5 animate-spin text-ink-500"
          />
        ) : selected ? (
          <button
            type="button"
            data-no-reorder="true"
            onMouseDown={(event) => event.preventDefault()}
            onClick={clear}
            className="absolute right-3 top-2.5 p-1 rounded-lg text-ink-500 hover:text-ink-100 hover:bg-ink-800"
            title="Clear selected series"
          >
            <X size={17} />
          </button>
        ) : null}

        {focused && (
          <div className="absolute z-40 left-0 right-0 mt-2 max-h-80 overflow-y-auto rounded-xl border border-ink-700 bg-ink-950 shadow-2xl">
            {options.length === 0 && !loading ? (
              <div className="px-4 py-4 text-sm text-ink-500">
                {emptyText}
              </div>
            ) : (
              options.map((option) => {
                const active = selected?.id === option.id;

                return (
                  <button
                    key={option.id}
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(option)}
                    className={`w-full min-w-0 px-4 py-3 text-left border-b border-ink-900 last:border-b-0 hover:bg-ink-900 flex items-start justify-between gap-3 ${
                      active ? 'bg-brand-950/30' : ''
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-ink-100 truncate">
                        {option.title}
                      </span>
                      <span className="block text-xs text-ink-500 mt-0.5 truncate">
                        {option.slug}
                        {option.subtitle ? ` · ${option.subtitle}` : ''}
                      </span>
                    </span>

                    {active && (
                      <CheckCircle2
                        size={17}
                        className="text-brand-400 shrink-0 mt-0.5"
                      />
                    )}
                  </button>
                );
              })
            )}
          </div>
        )}
      </div>

      {selected && (
        <div className="mt-2 min-w-0 rounded-lg border border-brand-900/50 bg-brand-950/20 px-3 py-2 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{selected.title}</div>
            <div className="text-xs text-ink-500 truncate">{selected.slug}</div>
          </div>
          <CheckCircle2 size={17} className="text-brand-400 shrink-0" />
        </div>
      )}

      {showSelectFallback && (
        <div className="relative mt-3">
          <select
            value={selected?.id ?? ''}
            onChange={(event) => {
              const option =
                selectOptions.find((item) => item.id === event.target.value) ??
                null;
              onSelect(option);
              if (option) onQueryChange(option.title);
            }}
            className="w-full appearance-none px-4 py-3 pr-10 bg-ink-950 border border-ink-800 rounded-xl text-ink-100 focus:border-brand-500 focus:outline-none"
          >
            <option value="">Or choose from current search results…</option>
            {selectOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.title}
                {option.subtitle ? ` — ${option.subtitle}` : ''}
              </option>
            ))}
          </select>
          <ChevronDown
            size={17}
            className="pointer-events-none absolute right-3 top-3.5 text-ink-500"
          />
        </div>
      )}
    </div>
  );
}
