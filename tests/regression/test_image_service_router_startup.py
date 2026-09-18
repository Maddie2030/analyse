from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
IMAGE_APP = ROOT / "services" / "image_service" / "app"


def module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


class ImageServiceRouterStartupContractTests(unittest.TestCase):
    def test_jobs_does_not_import_upload_router_module(self) -> None:
        imports = module_imports(IMAGE_APP / "routers" / "jobs.py")
        self.assertNotIn(
            "app.routers.upload",
            imports,
            "jobs.py must not depend on upload.py; upload.py delegates thumbnail jobs back to jobs.py",
        )

    def test_shared_upload_validation_contract_is_neutral(self) -> None:
        contract = IMAGE_APP / "media_validation.py"
        self.assertTrue(contract.exists(), "shared media validation contract module is missing")
        source = contract.read_text(encoding="utf-8") if contract.exists() else ""
        for symbol in ("SAFE_SLUG", "THUMBNAIL_NAME", "IMAGE_MIME_TYPES", "ARCHIVE_MIME_TYPES"):
            self.assertIn(symbol, source, f"media validation contract is missing {symbol}")

        jobs = (IMAGE_APP / "routers" / "jobs.py").read_text(encoding="utf-8")
        upload = (IMAGE_APP / "routers" / "upload.py").read_text(encoding="utf-8")
        self.assertIn("from app.media_validation import", jobs)
        self.assertIn("from app.media_validation import", upload)


if __name__ == "__main__":
    unittest.main()
