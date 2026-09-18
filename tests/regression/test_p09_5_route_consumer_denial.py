import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "contracts" / "ownership" / "routes.v1.json"
USER_GATEWAY = ROOT / "deploy" / "docker-desktop-hybrid" / "Caddyfile.user"
ADMIN_GATEWAY = ROOT / "deploy" / "docker-desktop-hybrid" / "Caddyfile.admin"
WEB_CLIENT = ROOT / "frontend" / "src" / "api" / "client.ts"
ANDROID_API = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "core" / "network" / "MReaderApiAdapter.kt"
ANDROID_SERVICE = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "mreader" / "android" / "core" / "network" / "MReaderApiService.kt"
ROUTE_AUDIT = ROOT / "scripts" / "tests" / "api-route-audit.py"
CATALOG_EVENTS = ROOT / "services" / "catalog_go" / "internal" / "store" / "events.go"
PROGRESS_EVENTS = ROOT / "services" / "progress_go" / "internal" / "store" / "events.go"
MEDIA_EVENTS = ROOT / "services" / "image_service" / "app" / "events.py"
OUTBOX_PUBLISHER = ROOT / "services" / "outbox_relay" / "internal" / "broker" / "publisher.go"

RETIRED_ROUTE_PREFIXES = (
    "/api/token/page",
    "/api/scraper/admin/backups",
    "/api/scraper/admin/database",
)


def load_routes():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["routes"]


class P095RouteConsumerDenialTests(unittest.TestCase):
    def test_both_gateways_explicitly_deny_known_retired_routes_before_catchalls(self):
        for path in (USER_GATEWAY, ADMIN_GATEWAY):
            text = path.read_text(encoding="utf-8")
            self.assertIn("@retiredApi path", text, path)
            self.assertIn("handle @retiredApi", text, path)
            self.assertRegex(text, r'handle @retiredApi\s*\{\s*respond "not found" 404\s*\}')
            for retired in RETIRED_ROUTE_PREFIXES:
                self.assertIn(retired, text, f"{path.name} does not deny {retired}")
                self.assertIn(f"{retired}/*", text, f"{path.name} does not deny descendants of {retired}")

            retired_pos = text.index("handle @retiredApi")
            fallback_positions = [
                pos for marker in (
                    "handle @adminApi",
                    "handle @scraper",
                    "handle @token",
                    "handle {",
                )
                if (pos := text.find(marker)) >= 0
            ]
            self.assertTrue(fallback_positions, path)
            self.assertLess(retired_pos, min(fallback_positions), f"{path.name} retired denial is after a broader catch-all")


    def test_public_gateway_denies_internal_admin_and_catalog_write_surfaces(self):
        user = USER_GATEWAY.read_text(encoding="utf-8")
        self.assertRegex(user, r'@internal path /internal /internal/\*\s+respond @internal 404')
        self.assertRegex(user, r'handle @adminApi\s*\{\s*respond "not found" 404\s*\}')
        self.assertRegex(user, r'handle @catalogWrite\s*\{\s*respond "not found" 404\s*\}')
        for prefix in (
            "/api/admin/database",
            "/api/scraper",
            "/api/upload",
            "/api/catalog/admin",
            "/api/auth/admin",
            "/api/notifications/admin",
        ):
            self.assertIn(prefix, user, f"public gateway does not explicitly fence {prefix}")

        admin = ADMIN_GATEWAY.read_text(encoding="utf-8")
        self.assertRegex(admin, r'@internal path /internal /internal/\*\s+respond @internal 404')

        for client in (WEB_CLIENT, ANDROID_SERVICE):
            text = client.read_text(encoding="utf-8")
            self.assertNotIn("/internal/", text, f"browser/mobile client consumes private route in {client}")

    def test_android_adapter_consumes_only_current_non_admin_manifest_routes(self):
        manifest = {(row["method"], row["path"]): row for row in load_routes()}
        source = ANDROID_SERVICE.read_text(encoding="utf-8")
        declared = re.findall(r'@(GET|POST|PUT|PATCH|DELETE)\("([^"]+)"\)', source)
        self.assertTrue(declared)
        for method, raw_path in declared:
            path = "/" + raw_path.lstrip("/")
            if path == "/healthz":
                continue
            self.assertIn((method, path), manifest, f"Android route is not current manifest authority: {method} {path}")
            self.assertNotIn(manifest[(method, path)]["access_plane"], {"admin", "internal"}, f"Android consumes forbidden route: {method} {path}")

    def test_registered_internal_media_routes_are_in_source_audit_and_manifest(self):
        spec = importlib.util.spec_from_file_location("p095_route_audit", ROUTE_AUDIT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)

        expected = {
            ("POST", "/internal/v1/media/jobs/thumbnail/{series_slug}"),
            ("GET", "/internal/v1/media/jobs/{job_id}"),
            ("POST", "/internal/v1/media/jobs/chapter/{series_slug}/{chapter_slug}"),
        }
        source = {(record.method, record.path) for record in audit.source_route_records()}
        manifest = {(row["method"], row["path"]) for row in load_routes()}
        self.assertTrue(expected <= source, f"registered internal Media routes missing from source audit: {sorted(expected - source)}")
        self.assertTrue(expected <= manifest, f"registered internal Media routes missing from ownership manifest: {sorted(expected - manifest)}")

    def test_manifest_declares_only_proven_direct_route_event_effects(self):
        expected = {
            ("POST", "/internal/v1/catalog/publications"): {"chapter.published", "series.updated"},
            ("PUT", "/api/catalog/series/{seriesID}"): {"series.updated"},
            ("PUT", "/internal/v1/catalog/series/{seriesID}/cover"): {"series.updated"},
            ("POST", "/api/progress/{seriesSlug}/{chapterSlug}/open"): {"progress.updated"},
            ("POST", "/api/progress/{seriesSlug}/{chapterSlug}/commit"): {"progress.updated"},
            ("POST", "/api/upload/jobs/chapter/{series_slug}/{chapter_slug}"): {"media.uploaded"},
            ("POST", "/internal/v1/media/jobs/chapter/{series_slug}/{chapter_slug}"): {"media.uploaded"},
            ("POST", "/api/upload/jobs/thumbnail/{series_slug}"): {"media.uploaded"},
            ("POST", "/internal/v1/media/jobs/thumbnail/{series_slug}"): {"media.uploaded"},
            ("POST", "/api/upload/series/{series_slug}/thumbnail"): {"media.uploaded"},
        }
        by_key = {(row["method"], row["path"]): row for row in load_routes()}
        for key, names in expected.items():
            self.assertIn(key, by_key)
            declared = {event["name"] for event in by_key[key]["events"] if event["direction"] == "publish"}
            self.assertEqual(names, declared, f"route event contract drift for {key}")

        declared_names = {event["name"] for row in load_routes() for event in row["events"]}
        self.assertNotIn("media.processed", declared_names, "worker-terminal event must not be attributed to an HTTP acceptance route")
        for name in declared_names:
            self.assertTrue(
                any((ROOT / "contracts" / "events" / version / f"{name}.schema.json").is_file() for version in ("v2", "v1")),
                f"declared event has no versioned schema: {name}",
            )

    def test_gateways_stamp_domain_owner_on_proxied_api_responses(self):
        expected = {
            USER_GATEWAY: {
                "@catalog": "catalog",
                "@auth": "auth",
                "@mobile": "reader",
                "@reader": "reader",
                "@token": "reader",
                "@realtime": "realtime",
                "@progress": "progress",
                "@social": "social",
                "@notifications": "notifications",
                "@images": "reader",
            },
            ADMIN_GATEWAY: {
                "@databaseAdmin": "database-protection",
                "@scraper": "scraper",
                "@upload": "media",
                "@catalogAdmin": "catalog",
                "@catalogWrite": "catalog",
                "@catalogRead": "catalog",
                "@auth": "auth",
                "@mobile": "reader",
                "@reader": "reader",
                "@token": "reader",
                "@realtime": "realtime",
                "@progress": "progress",
                "@social": "social",
                "@notifications": "notifications",
                "@images": "reader",
            },
        }
        for path, mappings in expected.items():
            text = path.read_text(encoding="utf-8")
            for marker, owner in mappings.items():
                start = text.index(f"handle {marker} {{")
                next_handle = text.find("\n    handle ", start + 1)
                segment = text[start:] if next_handle < 0 else text[start:next_handle]
                self.assertIn(
                    f"header_down X-MReader-Owner {owner}",
                    segment,
                    f"{path.name} {marker} does not stamp owner {owner}",
                )


    def test_event_transport_preserves_safe_owner_request_operation_revision_and_error_metadata(self):
        publisher = OUTBOX_PUBLISHER.read_text(encoding="utf-8")
        self.assertRegex(publisher, r"Metadata\s+map\[string\]any\s+`json:\"metadata,omitempty\"`")
        for field in ("owner", "request_id", "operation_id", "revision", "error_code", "retryable"):
            self.assertIn(f'"{field}"', publisher, f"outbox relay does not allow safe metadata field {field}")

        catalog = CATALOG_EVENTS.read_text(encoding="utf-8")
        for field in ("owner", "request_id", "operation_id", "revision"):
            self.assertIn(f'"{field}"', catalog, f"Catalog events do not propagate {field}")

        progress = PROGRESS_EVENTS.read_text(encoding="utf-8")
        for field in ("owner", "request_id", "revision"):
            self.assertIn(f'"{field}"', progress, f"Progress events do not propagate {field}")

        media = MEDIA_EVENTS.read_text(encoding="utf-8")
        for field in ("owner", "request_id", "operation_id", "revision", "error_code"):
            self.assertIn(f'"{field}"', media, f"Media events do not propagate {field}")

    def test_web_error_contract_preserves_safe_domain_metadata_and_request_id(self):
        text = WEB_CLIENT.read_text(encoding="utf-8")
        api_error = re.search(r"export interface ApiError\s*\{(?P<body>.*?)\n\}", text, re.S)
        self.assertIsNotNone(api_error)
        body = api_error.group("body")
        for field in ("code", "owner", "request_id", "operation_id", "revision", "retryable"):
            self.assertRegex(body, rf"\b{field}\??\s*:", f"ApiError does not preserve {field}")
        self.assertIn("X-Request-ID", text)
        self.assertIn("apiErrorFromResponse", text)
        self.assertIn("response.headers.get('X-Request-ID')", text)
        self.assertIn("response.headers.get('X-MReader-Owner')", text)

    def test_web_api_calls_do_not_bypass_shared_metadata_transport(self):
        source = WEB_CLIENT.read_text(encoding="utf-8")
        direct_api_fetches = re.findall(r"fetch\(\s*[`\"']\/api\/[^\n]*", source)
        self.assertEqual([], direct_api_fetches, "direct /api fetch bypasses request metadata transport")

    def test_android_error_contract_preserves_safe_domain_metadata_and_request_id(self):
        text = ANDROID_API.read_text(encoding="utf-8")
        api_error = re.search(r"class ApiException\((?P<body>.*?)\)\s*:\s*IOException", text, re.S)
        self.assertIsNotNone(api_error)
        body = api_error.group("body")
        for field in ("code", "owner", "requestId", "operationId", "revision", "retryable"):
            self.assertRegex(body, rf"\b{field}\s*:", f"Android ApiException does not preserve {field}")
        self.assertIn('response.headers()["X-Request-ID"]', text)
        self.assertIn('response.headers()["X-MReader-Owner"]', text)
        self.assertIn('response.raw().request.header("X-Request-ID")', text)


if __name__ == "__main__":
    unittest.main()
