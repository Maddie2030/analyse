\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM series) OR EXISTS (SELECT 1 FROM chapters) OR EXISTS (SELECT 1 FROM pages) THEN
    RAISE EXCEPTION 'catalog import requires an empty target catalog';
  END IF;
END $$;

CREATE TEMP TABLE recovery_genres (LIKE genres INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_tags (LIKE tags INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_series (LIKE series INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_chapters (LIKE chapters INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_pages (LIKE pages INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_series_genres (LIKE series_genres INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE recovery_series_tags (LIKE series_tags INCLUDING DEFAULTS) ON COMMIT DROP;

\copy recovery_genres(id,name) FROM '/tmp/mreader-catalog-recovery/genres.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_tags(id,name) FROM '/tmp/mreader-catalog-recovery/tags.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_series(id,title,slug,description,cover_image_path,status,created_at,updated_at) FROM '/tmp/mreader-catalog-recovery/series.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_chapters(id,series_id,chapter_number,title,slug,status,page_count,created_at,updated_at) FROM '/tmp/mreader-catalog-recovery/chapters.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_pages(id,chapter_id,page_number,image_path,width,height,responsive_image_path,responsive_width,responsive_height,encoding_version,encoding_rows,encoding_columns,encoding_seed) FROM '/tmp/mreader-catalog-recovery/pages.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_series_genres(series_id,genre_id) FROM '/tmp/mreader-catalog-recovery/series_genres.csv' WITH (FORMAT csv, HEADER true)
\copy recovery_series_tags(series_id,tag_id) FROM '/tmp/mreader-catalog-recovery/series_tags.csv' WITH (FORMAT csv, HEADER true)

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM recovery_chapters c
    LEFT JOIN recovery_series s ON s.id=c.series_id
    WHERE s.id IS NULL
  ) THEN RAISE EXCEPTION 'recovery catalog contains orphan chapters'; END IF;

  IF EXISTS (
    SELECT 1 FROM recovery_pages p
    LEFT JOIN recovery_chapters c ON c.id=p.chapter_id
    WHERE c.id IS NULL
  ) THEN RAISE EXCEPTION 'recovery catalog contains orphan pages'; END IF;

  IF EXISTS (
    SELECT 1 FROM recovery_pages
    WHERE encoding_version <> 4
       OR encoding_seed IS NULL OR length(encoding_seed) < 16
       OR encoding_rows NOT BETWEEN 1 AND 32
       OR encoding_columns NOT BETWEEN 1 AND 32
       OR image_path IS NULL OR btrim(image_path) = ''
  ) THEN RAISE EXCEPTION 'recovery catalog contains invalid v4 page metadata'; END IF;

  IF EXISTS (
    SELECT series_id, chapter_number FROM recovery_chapters GROUP BY 1,2 HAVING count(*) > 1
  ) OR EXISTS (
    SELECT series_id, slug FROM recovery_chapters GROUP BY 1,2 HAVING count(*) > 1
  ) OR EXISTS (
    SELECT chapter_id, page_number FROM recovery_pages GROUP BY 1,2 HAVING count(*) > 1
  ) THEN RAISE EXCEPTION 'recovery catalog contains duplicate chapter/page identity'; END IF;
END $$;

-- The fresh schema seeds tags. For a catalog-only disaster recovery, replace
-- taxonomy with the donor IDs so series_tags/series_genres remain exact.
DELETE FROM series_tags;
DELETE FROM series_genres;
DELETE FROM tags;
DELETE FROM genres;

INSERT INTO genres(id,name) SELECT id,name FROM recovery_genres ORDER BY id;
INSERT INTO tags(id,name) SELECT id,name FROM recovery_tags ORDER BY id;
INSERT INTO series(id,title,slug,description,cover_image_path,status,created_at,updated_at)
SELECT id,title,slug,description,cover_image_path,status,created_at,updated_at FROM recovery_series ORDER BY created_at,id;
INSERT INTO chapters(id,series_id,chapter_number,title,slug,status,page_count,created_at,updated_at)
SELECT id,series_id,chapter_number,title,slug,status,page_count,created_at,updated_at FROM recovery_chapters ORDER BY series_id,chapter_number,id;
INSERT INTO pages(id,chapter_id,page_number,image_path,width,height,responsive_image_path,responsive_width,responsive_height,encoding_version,encoding_rows,encoding_columns,encoding_seed)
SELECT id,chapter_id,page_number,image_path,width,height,responsive_image_path,responsive_width,responsive_height,encoding_version,encoding_rows,encoding_columns,encoding_seed FROM recovery_pages ORDER BY chapter_id,page_number,id;
INSERT INTO series_genres(series_id,genre_id) SELECT series_id,genre_id FROM recovery_series_genres ORDER BY series_id,genre_id;
INSERT INTO series_tags(series_id,tag_id) SELECT series_id,tag_id FROM recovery_series_tags ORDER BY series_id,tag_id;

SELECT setval(pg_get_serial_sequence('genres','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM genres;
SELECT setval(pg_get_serial_sequence('tags','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM tags;

COMMIT;
