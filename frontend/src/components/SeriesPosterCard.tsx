import { Bookmark, Star, Users } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Series, SeriesSocialMetrics } from '../api/client';

export default function SeriesPosterCard({
  series,
  metrics,
  dense = false,
}: {
  series: Series;
  metrics?: SeriesSocialMetrics;
  dense?: boolean;
}) {
  return (
    <Link to={`/series/${series.slug}`} className="group min-w-0">
      <div className="relative aspect-[2/3] overflow-hidden rounded-xl bg-ink-800">
        {series.cover_image_path ? (
          <img
            src={`/images/${series.cover_image_path}`}
            alt={series.title}
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-ink-700 to-ink-800">
            <span className="font-display text-3xl font-bold text-ink-500">{series.title[0]}</span>
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-950 via-ink-950/65 to-transparent p-2 pt-8">
          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize ${
            series.status === 'ongoing'
              ? 'bg-green-600/80'
              : series.status === 'completed'
                ? 'bg-blue-600/80'
                : series.status === 'cancelled'
                  ? 'bg-red-600/80'
                  : 'bg-yellow-600/80'
          }`}>
            {series.status || 'ongoing'}
          </span>
        </div>
      </div>
      <h3 className={`${dense ? 'text-xs sm:text-sm' : 'text-sm'} mt-2 min-w-0 line-clamp-2 break-words font-medium transition-colors group-hover:text-brand-400`}>
        {series.title}
      </h3>
      {metrics && (
        <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-400">
          <span className="inline-flex items-center gap-1">
            <Star size={12} className="text-amber-400" fill="currentColor" />
            {metrics.rating_average?.toFixed(1) ?? '—'}
          </span>
          <span className="inline-flex items-center gap-1" title="Bookmarks">
            <Bookmark size={12} className="text-brand-400" />
            {metrics.bookmark_count}
          </span>
          <span className="inline-flex items-center gap-1" title="Subscribers">
            <Users size={12} className="text-brand-400" />
            {metrics.subscription_count}
          </span>
        </div>
      )}
      {!dense && series.tags && series.tags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {series.tags.slice(0, 2).map((tag) => (
            <span key={tag.id} className="max-w-full rounded-full bg-brand-600/15 px-1.5 py-0.5 text-[10px] text-brand-300">
              {tag.name}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
