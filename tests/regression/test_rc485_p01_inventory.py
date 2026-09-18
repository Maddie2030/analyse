from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "docs/qualification/RC485-BASELINE-PROVENANCE.md"
CAPABILITIES = ROOT / "docs/qualification/RC485-CAPABILITY-MATRIX.md"
TABLES = ROOT / "docs/qualification/RC485-TABLE-DISPOSITION.md"

SURFACES = (
    "Browse/Search",
    "Series Detail",
    "Reader",
    "Library",
    "Account/Alerts",
    "Admin content",
    "Admin ingestion",
    "Admin curation",
    "Database Protection",
)

ARCHIVES = {
    "mreader-rc481-history-public-metrics-reliability(6).zip": "1188d087c7335bb0cda45218ff474fe8b6dc2751d67775ecac6c14deb41b65fb",
    "mreader-v1.3.0-rc4.84-continuity-recovery-r2(1).zip": "98aca244ba406b46c04392763bf2b9ff16a0714988f0ab411bd92c11f4921de7",
    "mreader-v1.3.0-rc4.84-continuity-recovery-r4(1).zip": "fe302f271e3929b78f89f0577d8eab366c943a8fa24ab0556fd7b269c3dff27e",
    "mreader-v1.3.0-rc4.84-continuity-recovery-r5(1).zip": "ab48e524e80c803913a992a3c46f2e936a4bcf238c43ada3975de79227885376",
}


def current_tables() -> set[str]:
    created: set[str] = set()
    dropped: set[str] = set()
    sources = [ROOT / "db/init.sql", *sorted((ROOT / "db/migrations").glob("*.sql"))]
    create_re = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    drop_re = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?[\"`]?([A-Za-z_][\w]*)", re.I)
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="ignore")
        created.update(m.group(1) for m in create_re.finditer(text))
        dropped.update(m.group(1) for m in drop_re.finditer(text))
    return created - dropped


class RC485P01InventoryTests(unittest.TestCase):
    def test_provenance_records_baseline_and_archive_identities(self):
        text = PROVENANCE.read_text(encoding="utf-8")
        self.assertIn("9a2415002983ea79915d7fb0a8a6cd2d83150fc0", text)
        self.assertIn("7d6b74c", text)
        self.assertIn("958e15800c53c95735c5f02412841d40eb17971d6ddd4d129752b46cdd4bb34c", text)
        self.assertIn("729/729", text)
        for name, digest in ARCHIVES.items():
            self.assertIn(name, text)
            self.assertIn(digest, text)
        for marker in ("SOURCE_SHA256SUMS.txt", "582", "85", "4"):
            self.assertIn(marker, text)

    def test_capability_matrix_covers_every_required_surface_with_source_and_test_evidence(self):
        text = CAPABILITIES.read_text(encoding="utf-8")
        for surface in SURFACES:
            self.assertIn(surface, text)
        self.assertIn("frontend/src/pages/Catalog.tsx", text)
        self.assertIn("android/app/src/main/java/com/mreader/android/ui/screens/CatalogScreen.kt", text)
        self.assertIn("tests/api/test_17_smart_library.py", text)
        self.assertIn("tests/api/test_25_database_protection.py", text)
        self.assertIn("tests/api/test_27_mobile_reader_adapter.py", text)
        self.assertNotRegex(text, r"\b(?:TODO|TBD)\b")

    def test_table_disposition_covers_current_and_retired_tables(self):
        text = TABLES.read_text(encoding="utf-8")
        documented = set(re.findall(r"`([a-z][a-z0-9_]*)`", text))
        missing = current_tables() - documented
        self.assertEqual(set(), missing, f"missing current table disposition rows: {sorted(missing)}")
        for retired in ("reading_history", "backup_requests"):
            self.assertIn(f"`{retired}`", text)
        self.assertIn("database_recovery_points", documented)
        self.assertNotRegex(text, r"\b(?:TODO|TBD)\b")

    def test_disposition_names_observed_competing_publication_writers(self):
        text = TABLES.read_text(encoding="utf-8")
        for evidence in (
            "services/scraper_service/app/publication.py",
            "services/scraper_service/app/series_drafts.py",
            "services/image_service/app/services/chapter_ingestion.py",
            "services/catalog_go/internal/store/store.go",
        ):
            self.assertIn(evidence, text)
        self.assertIn("Competing writer", text)


if __name__ == "__main__":
    unittest.main()
