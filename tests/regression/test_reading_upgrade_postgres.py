"""Real migration acceptance cases. Requires psql and an explicit disposable-test DSN.

No SQL mock: each case owns a newly created database, and drops only that database.
Run: MREADER_TEST_POSTGRES_DSN=... python3 -m unittest discover -s tests/regression \
    -p test_reading_upgrade_postgres.py -v
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get("MREADER_TEST_POSTGRES_DSN")
VERSIONS = ["047_consolidate_reading_state_rc482.sql", "048_rc483_current_baseline.sql",
            "051_progress_revision_ordering.sql", "052_reading_evidence_provenance.sql"]
U = "00000000-0000-0000-0000-000000000001"
S = "00000000-0000-0000-0000-000000000002"
A = "00000000-0000-0000-0000-000000000003"
B = "00000000-0000-0000-0000-000000000004"
C = "00000000-0000-0000-0000-000000000005"


def database_dsn(dsn, name):
    if dsn.startswith(("postgres://", "postgresql://")):
        uri = urllib.parse.urlsplit(dsn)
        query = [(k, v) for k, v in urllib.parse.parse_qsl(uri.query) if k != "dbname"]
        return urllib.parse.urlunsplit(uri._replace(path="/" + name, query=urllib.parse.urlencode(query)))
    if "=" not in dsn:
        dsn = "dbname='" + dsn.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return dsn + " dbname='" + name + "'"


@unittest.skipUnless(DSN and shutil.which("psql"), "blocked: psql and explicit MREADER_TEST_POSTGRES_DSN required")
class ReadingUpgradePostgresTests(unittest.TestCase):
    def setUp(self):
        self.name = "mreader_migration_test_" + uuid.uuid4().hex
        self.db = database_dsn(DSN, self.name)
        self.psql("CREATE DATABASE " + self.name + " TEMPLATE template0;", DSN)
        self.addCleanup(lambda: self.psql("DROP DATABASE IF EXISTS " + self.name + " WITH (FORCE);", DSN))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.migrations = Path(self.temp.name)
        for version in VERSIONS:
            shutil.copyfile(ROOT / "db/migrations" / version, self.migrations / version)
        self.env = dict(os.environ, MREADER_MIGRATIONS_DIR=str(self.migrations),
                        MREADER_READING_PRESERVATION_SQL=str(ROOT / "db/upgrade/preserve-reading-evidence.sql"))
        self.psql(f"""
CREATE TABLE users(id uuid PRIMARY KEY);
CREATE TABLE series(id uuid PRIMARY KEY, title text DEFAULT 'Fixture', slug text DEFAULT 'fixture',
                    cover_image_path text, status text DEFAULT 'ongoing');
CREATE TABLE chapters(id uuid PRIMARY KEY, series_id uuid REFERENCES series, chapter_number numeric,
                      page_count integer NOT NULL, status text DEFAULT 'published', title text DEFAULT 'Chapter',
                      slug text DEFAULT 'chapter', created_at timestamptz DEFAULT now());
CREATE TABLE bookmarks(id uuid DEFAULT gen_random_uuid(), user_id uuid, series_id uuid, created_at timestamptz DEFAULT now());
CREATE TABLE subscriptions(id uuid DEFAULT gen_random_uuid(), user_id uuid, series_id uuid, created_at timestamptz DEFAULT now());
CREATE TABLE reading_progress(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid REFERENCES users, series_id uuid REFERENCES series,
 chapter_id uuid REFERENCES chapters ON DELETE CASCADE, last_page integer NOT NULL DEFAULT 1,
 scroll_position double precision NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,series_id));
CREATE TABLE chapter_reads(user_id uuid REFERENCES users NOT NULL, series_id uuid REFERENCES series NOT NULL,
 chapter_id uuid REFERENCES chapters NOT NULL, first_read_at timestamptz NOT NULL DEFAULT now(),
 last_read_at timestamptz NOT NULL DEFAULT now(), last_page integer NOT NULL DEFAULT 1 CHECK(last_page>=1),
 completed boolean NOT NULL DEFAULT false, completed_at timestamptz, PRIMARY KEY(user_id,chapter_id));
CREATE TABLE reading_history(user_id uuid REFERENCES users, series_id uuid REFERENCES series,
 chapter_id uuid REFERENCES chapters ON DELETE SET NULL, furthest_chapter_id uuid REFERENCES chapters ON DELETE SET NULL,
 read_at timestamptz, UNIQUE(user_id,series_id));
CREATE TABLE notifications(kind text DEFAULT 'legacy');
CREATE TABLE schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
INSERT INTO users VALUES('{U}'); INSERT INTO series(id) VALUES('{S}');
INSERT INTO chapters(id,series_id,chapter_number,page_count) VALUES
 ('{A}','{S}',1,20),('{B}','{S}',2,5),('{C}','{S}',3,7);
""")

    def psql(self, sql, dsn=None):
        result = subprocess.run(["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-d", dsn or self.db],
                                input=sql, text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def start_runner(self):
        runner = subprocess.Popen(["sh", str(ROOT / "ops/migrate/apply.sh"), "-d", self.db],
                                  env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def close_runner():
            if runner.poll() is None:
                runner.terminate()
                try:
                    runner.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    runner.kill()
                    runner.wait(timeout=5)
            runner.stdout.close()
            runner.stderr.close()
        self.addCleanup(close_runner)
        return runner

    def apply(self, success=True):
        runner = self.start_runner()
        stdout, stderr = runner.communicate(timeout=45)
        if success:
            self.assertEqual(runner.returncode, 0, stderr)
        else:
            self.assertNotEqual(runner.returncode, 0, stdout)
        return stdout, stderr

    def seed(self, exact_c=False, reach_only=False):
        if not reach_only:
            self.psql(f"INSERT INTO reading_progress(user_id,series_id,chapter_id,last_page,scroll_position,updated_at) "
                      f"VALUES('{U}','{S}','{A}',18,0.75,'2026-01-01T10:00:00Z');")
        last = "NULL" if reach_only else "'" + B + "'"
        self.psql(f"INSERT INTO reading_history VALUES('{U}','{S}',{last},'{C}','2026-01-02T10:00:00Z');")
        if exact_c:
            self.psql(f"INSERT INTO chapter_reads VALUES('{U}','{S}','{C}','2025-12-30T09:00:00Z',"
                      "'2025-12-31T09:00:00Z',7,true,'2025-12-31T09:00:00Z');")

    def row(self, chapter):
        return json.loads(self.psql(f"SELECT row_to_json(cr) FROM chapter_reads cr WHERE chapter_id='{chapter}';"))

    def view(self):
        return json.loads(self.psql(f"SELECT row_to_json(rs) FROM reading_state_v1 rs WHERE user_id='{U}';"))

    def library_item(self):
        source = (ROOT / 'services/social_ts/src/routes.ts').read_text()
        base_sql = re.search(r'const SMART_LIBRARY_BASE_SQL = `([\s\S]*?)`;', source).group(1)
        return json.loads(self.psql("PREPARE library_projection(uuid) AS " + base_sql +
                                   f" SELECT row_to_json(base) FROM base; EXECUTE library_projection('{U}');"))

    def test_exact_checkpoint_history_and_furthest_remain_distinct(self):
        self.seed()
        self.apply()
        a, b, c = self.row(A), self.row(B), self.row(C)
        self.assertEqual((a['resume_page'], a['resume_scroll_position'], a['completed']), (18, 0.75, False))
        self.assertEqual((b['last_page'], b['completed']), (1, False))
        self.assertEqual((c['provenance'], c['resume_page'], c['completed']), ('migrated_reach', None, False))
        state = self.view()
        self.assertEqual((state['resume_chapter_id'], state['furthest_chapter_id'], state['has_history']), (B, C, True))
        self.assertEqual(self.psql("SELECT to_regclass('public.reading_history') IS NULL;"), 't')
        before = self.psql("SELECT md5(string_agg(row_to_json(cr)::text, '' ORDER BY chapter_id)) FROM chapter_reads cr;")
        self.apply()
        self.assertEqual(before, self.psql("SELECT md5(string_agg(row_to_json(cr)::text, '' ORDER BY chapter_id)) FROM chapter_reads cr;"))

    def test_exact_furthest_wins_over_inference(self):
        self.seed(exact_c=True)
        self.apply()
        c = self.row(C)
        self.assertEqual((c['completed'], c['last_page'], c['provenance']), (True, 7, 'legacy'))
        self.assertTrue(c['first_read_at'].startswith('2025-12-30'))

    def test_reach_only_never_becomes_exact_history_or_resume(self):
        self.seed(reach_only=True)
        self.apply()
        state = self.view()
        self.assertEqual((state['has_history'], state['resume_chapter_id'], state['last_opened_at'],
                          state['last_opened_chapter_id'], state['furthest_chapter_id']), (False, None, None, None, C))
        self.assertIsNone(self.row(C)['resume_page'])

    def test_library_preserves_inferred_reach_without_fabricating_recency(self):
        self.seed(reach_only=True)
        self.psql(f"INSERT INTO chapters(id,series_id,chapter_number,page_count,slug) VALUES"
                  f"('00000000-0000-0000-0000-000000000006','{S}',4,10,'ch-4');")
        self.apply()
        item = self.library_item()
        self.assertEqual((item['has_history'], item['read_at'], item['resume_chapter_id']), (False, None, None))
        self.assertEqual((item['furthest_chapter_id'], item['unread_chapter_count'], item['read_state']), (C, 1, 'updates'))
        self.assertEqual(item['reading_action']['chapter_slug'], 'ch-4')

    def test_partial_upgrade_also_preserves_before_048(self):
        self.seed()
        self.psql("INSERT INTO schema_migrations(version) VALUES('" + VERSIONS[0] + "');")
        self.apply()
        self.assertEqual(self.row(C)['provenance'], 'migrated_reach')
        self.assertEqual(self.row(B)['last_page'], 1)

    def test_already_retired_history_repairs_only_surviving_checkpoint(self):
        self.seed()
        self.psql("DROP TABLE reading_history;")
        self.psql("INSERT INTO schema_migrations(version) VALUES('" + VERSIONS[0] + "'),('" + VERSIONS[1] + "');")
        self.apply()
        self.assertEqual(self.view()['furthest_chapter_id'], A)
        self.assertEqual(self.psql("SELECT count(*) FROM chapter_reads;"), '1')
        self.assertEqual(self.row(A)['resume_page'], 18)

    def test_absent_history_with_047_pending_is_safe(self):
        self.psql("DROP TABLE reading_history;")
        self.apply()
        self.assertEqual(self.psql("SELECT count(*) FROM chapter_reads;"), '0')

    def test_preservation_and_ledger_roll_back_with_original_migration_failure(self):
        self.seed()
        path = self.migrations / VERSIONS[0]
        path.write_text(path.read_text() + "\nSELECT rc485_intentional_missing_function();\n")
        self.apply(success=False)
        self.assertEqual(self.psql("SELECT count(*) FROM reading_history;"), '1')
        self.assertEqual(self.psql("SELECT count(*) FROM chapter_reads;"), '0')
        self.assertEqual(self.psql("SELECT count(*) FROM schema_migrations;"), '0')

    def test_invalid_history_link_blocks_deletion(self):
        self.seed()
        self.psql("INSERT INTO series(id) VALUES('00000000-0000-0000-0000-000000000009'); "
                  f"UPDATE chapters SET series_id='00000000-0000-0000-0000-000000000009' WHERE id='{C}';")
        self.apply(success=False)
        self.assertEqual(self.psql("SELECT count(*) FROM reading_history;"), '1')

    def test_concurrent_runners_apply_each_migration_once(self):
        self.seed()
        (self.migrations / '053_concurrency_fixture.sql').write_text(
            "CREATE TABLE migration_race_probe(value int);\nSELECT pg_sleep(0.3);\nINSERT INTO migration_race_probe VALUES(1);\n")
        runners = [self.start_runner(), self.start_runner()]
        for runner in runners:
            _, stderr = runner.communicate(timeout=45)
            self.assertEqual(runner.returncode, 0, stderr)
        self.assertEqual(self.psql("SELECT count(*) FROM migration_race_probe;"), '1')
        self.assertEqual(self.psql("SELECT count(*) FROM schema_migrations WHERE version='053_concurrency_fixture.sql';"), '1')


if __name__ == '__main__':
    unittest.main()
