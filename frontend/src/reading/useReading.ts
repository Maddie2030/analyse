import { useSyncExternalStore } from 'react';
import { readingRepository, readingVersion, subscribeReading } from './browser';
import { pendingPreview } from './model';
export function useReading(seriesId?: string) {
  useSyncExternalStore(subscribeReading, readingVersion);
  const repository = readingRepository();
  return { repository, pending: seriesId ? pendingPreview(repository?.records() || [], seriesId) : null };
}
