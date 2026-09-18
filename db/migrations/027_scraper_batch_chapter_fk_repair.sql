-- Repair scraper batch chapter lifecycle semantics.
--
-- Batch rows are workflow/history records. During an overwrite publish the old
-- chapter is intentionally deleted before its replacement is created. CASCADE
-- on existing_chapter_id therefore deleted the *job row that was performing the
-- overwrite*, producing missing batch items and inconsistent chapter counts.
-- Keep the durable batch item and clear chapter references instead.

ALTER TABLE scraper_batch_items
    DROP CONSTRAINT IF EXISTS scraper_batch_items_existing_chapter_id_fkey;
ALTER TABLE scraper_batch_items
    ADD CONSTRAINT scraper_batch_items_existing_chapter_id_fkey
    FOREIGN KEY (existing_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL;

ALTER TABLE scraper_batch_items
    DROP CONSTRAINT IF EXISTS scraper_batch_items_published_chapter_id_fkey;
ALTER TABLE scraper_batch_items
    ADD CONSTRAINT scraper_batch_items_published_chapter_id_fkey
    FOREIGN KEY (published_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL;

COMMENT ON COLUMN scraper_batch_items.existing_chapter_id IS
    'Existing chapter selected for overwrite/skip decisions. SET NULL preserves the batch workflow row if the chapter is replaced/deleted.';
COMMENT ON COLUMN scraper_batch_items.published_chapter_id IS
    'Published chapter produced by the batch item. SET NULL preserves scraper history when the published chapter is later deleted.';
