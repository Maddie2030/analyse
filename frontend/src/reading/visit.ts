import type { CanonicalReading, Target } from './model.ts';
import type { ReadingRepository } from './repository.ts';
type Position = { last_page: number; scroll_position: number };
type Options = { id?: string; repository: ReadingRepository; target: Target;
  read?: () => Promise<CanonicalReading>; restore: (position: Position) => void };
// A visit owns immediate local intent even while remote restoration is pending.
export class ReadingVisit {
  readonly id: string;
  readonly ready: Promise<void>;
  private options: Options;
  private interacted = false;
  private closed = false;
  private restored = false;
  private restorePosition: Position | undefined;
  constructor(options: Options) {
    this.options = options;
    this.id = options.id || options.repository.beginOpen(options.target, null);
    options.repository.holdOpen(this.id);
    this.ready = this.initialize();
  }
  private async initialize() {
    const { repository, target, read } = this.options;
    await repository.load();
    const local = repository.records().filter(r => r.id !== this.id && r.target.chapter_id === target.chapter_id && r.dirty)
      .sort((a, b) => b.touched - a.touched || b.created - a.created)[0];
    let canonical = repository.confirmed(target.series_id);
    try { if (read) canonical = await read(); } catch { /* Use only the last observed revision while offline. */ }
    this.restorePosition = local?.position || (canonical?.chapter_id === target.chapter_id
      ? { last_page: canonical.last_page, scroll_position: canonical.scroll_position } : undefined);
    await repository.resolveOpen(this.id, canonical?.revision || 0);
    // The durable intent is resolved after exit too, but navigation never is.
  }
  capture(page: number, scroll: number, completedPage: number, userInteraction = false) {
    if (this.closed) return;
    if (userInteraction) this.interacted = true;
    this.options.repository.checkpoint(this.id, page, scroll, completedPage);
  }
  interact() { this.interacted = true; }
  restoreWhenReady() {
    if (this.closed || this.interacted || this.restored || !this.restorePosition) return;
    this.restored = true;
    const position = { last_page: Math.min(Math.max(1, this.restorePosition.last_page), Math.max(1, this.options.target.page_count)),
      scroll_position: Math.min(1, Math.max(0, this.restorePosition.scroll_position)) };
    this.options.restore(position);
  }
  close() { this.closed = true; void this.options.repository.persist(); }
}
