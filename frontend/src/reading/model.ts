export type OpenIntent = { command_id: string; expected_revision: number };
export type CommitIntent = { command_id: string; session_generation: number; command_sequence: number; last_page: number; scroll_position: number; completed: boolean; completed_page: number };
export type CanonicalReading = {
  series_id: string; chapter_id: string; last_page: number; scroll_position: number;
  updated_at?: string | null; last_opened_at?: string | null;
  revision: number; session_generation: number; command_sequence: number;
  accepted?: boolean; duplicate?: boolean; code?: string; command_id?: string;
};
export type Target = { series_id: string; chapter_id: string; series_slug: string; chapter_slug: string; page_count: number };
export type ReadingRecord = {
  id: string; target: Target; created: number; touched: number; version: string;
  position: { last_page: number; scroll_position: number }; completed_page: number;
  dirty: boolean; session_generation: number; sequence: number; paused: string | null;
  command: { kind: 'open'; body: OpenIntent; version: string; sent: boolean; awaiting_revision?: boolean; depends_on?: string } | { kind: 'commit'; body: CommitIntent; version: string; sent: boolean } | null;
};
export const scopeKey = (origin: string, account: string | null) => JSON.stringify([origin, account]);
export function createRecord(target: Target, revision: number, id: string, now: number): ReadingRecord {
  return { id, target, created: now, touched: now, version: id, position: { last_page: 1, scroll_position: 0 }, completed_page: 0,
    dirty: false, session_generation: 0, sequence: 0, paused: null,
    command: { kind: 'open', body: { command_id: id, expected_revision: revision }, version: id, sent: false } };
}
export function checkpoint(r: ReadingRecord, page: number, scroll: number, completedPage: number, version: string): ReadingRecord {
  const position = { last_page: Math.min(Math.max(1, Math.floor(page)), Math.max(1, r.target.page_count)), scroll_position: Math.min(1, Math.max(0, scroll)) };
  const completion = Math.max(r.completed_page, completedPage === r.target.page_count ? completedPage : 0);
  if (position.last_page === r.position.last_page && position.scroll_position === r.position.scroll_position && completion === r.completed_page) return r;
  return { ...r, position, completed_page: completion, version, dirty: true };
}
export function prepare(r: ReadingRecord, id: string): ReadingRecord {
  if (r.command || r.paused || !r.dirty || !r.session_generation) return r;
  return { ...r, command: { kind: 'commit', version: r.version, sent: false, body: { command_id: id, session_generation: r.session_generation,
    command_sequence: r.sequence + 1, ...r.position, completed: r.completed_page > 0, completed_page: r.completed_page } } };
}
export function acknowledge(r: ReadingRecord, value: CanonicalReading): ReadingRecord {
  if (!r.command || value.command_id !== r.command.body.command_id) return r;
  if (!value.accepted) return { ...r, paused: value.code || 'invalid_response' };
  const opening = r.command.kind === 'open';
  const validOrder = (order: number, minimum: number) => Number.isSafeInteger(order) && order >= minimum;
  if (value.series_id !== r.target.series_id || value.chapter_id !== r.target.chapter_id ||
      !validOrder(value.revision, 0) || !validOrder(value.session_generation, 1) || !validOrder(value.command_sequence, 0)) {
    return { ...r, paused: 'invalid_response' };
  }
  if (!opening) {
    const body = r.command.body as CommitIntent;
    if (value.session_generation !== body.session_generation || value.command_sequence !== body.command_sequence) {
      return { ...r, paused: 'invalid_response' };
    }
  }
  return { ...r, command: null, paused: null,
    session_generation: opening ? value.session_generation : r.session_generation,
    sequence: opening ? value.command_sequence : (r.command.body as CommitIntent).command_sequence,
    dirty: opening ? r.dirty : r.version !== r.command.version,
    position: opening && !r.dirty && value.chapter_id === r.target.chapter_id
      ? { last_page: value.last_page, scroll_position: value.scroll_position } : r.position };
}
export function pendingPreview(records: ReadingRecord[], seriesId: string) {
  const relevant = records.filter(r => r.target.series_id === seriesId && (r.dirty || r.command));
  const r = relevant.sort((a, b) => b.touched - a.touched || b.created - a.created || b.id.localeCompare(a.id))[0];
  const paused = relevant.filter(r => r.paused).sort((a, b) => a.created - b.created || a.id.localeCompare(b.id))[0];
  return r ? { chapter_id: r.target.chapter_id, chapter_slug: r.target.chapter_slug, ...r.position,
    status: paused ? 'Sync paused' : 'Saving', paused_record_id: paused?.id || null } : null;
}
export function completionEvidence(endObserved: boolean, pages: number[], loaded: Set<number>, pageCount: number) {
  return endObserved && pageCount > 0 && pages.length === pageCount && pages.every(page => loaded.has(page)) ? pageCount : 0;
}

// Only the primary local action is overlaid; server read markers/counts stay intact.
export function seriesReadingAction(seriesSlug: string, state: { resume_chapter_slug?: string | null; resume_chapter_number?: number | null } | null,
  first: { slug: string } | null | undefined, pending: ReturnType<typeof pendingPreview>, storageError = '') {
  if (pending) return { href: `/read/${seriesSlug}/${pending.chapter_slug}`, label: 'CONTINUE READING',
    status: `Local page ${pending.last_page} · ${storageError || pending.status}` };
  if (state?.resume_chapter_slug) return { href: `/read/${seriesSlug}/${state.resume_chapter_slug}`,
    label: state.resume_chapter_number != null ? `CONTINUE CH. ${state.resume_chapter_number}` : 'CONTINUE READING', status: '' };
  return first ? { href: `/read/${seriesSlug}/${first.slug}`, label: 'START READING', status: '' } : null;
}
