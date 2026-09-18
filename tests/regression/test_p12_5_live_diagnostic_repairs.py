import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class P125LiveDiagnosticRepairTests(unittest.TestCase):
    def test_api_harness_exports_actor_media_helpers_and_asyncpg(self):
        helpers = (ROOT / 'tests/api/helpers.py').read_text(encoding='utf-8')
        requirements = (ROOT / 'tests/api/requirements.txt').read_text(encoding='utf-8')
        self.assertIn('def zip_image_chapter(', helpers)
        self.assertIn('def wait_series_draft_terminal(', helpers)
        self.assertIn('asyncpg==0.30.0', requirements)


    def test_json_fetch_is_canonical_on_api_session(self):
        helper_tree = ast.parse((ROOT / "tests/api/helpers.py").read_text(encoding="utf-8"))
        api_session = next(
            node for node in helper_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ApiSession"
        )
        self.assertIn("get_json", {node.name for node in api_session.body if isinstance(node, ast.FunctionDef)})

        waiter = next(
            node for node in helper_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "wait_series_draft_terminal"
        )
        self.assertFalse(any(isinstance(node, ast.FunctionDef) for node in waiter.body))
        self.assertTrue(any(
            isinstance(node, ast.Attribute) and node.attr == "get_json"
            for node in ast.walk(waiter)
        ))

        reader_tree = ast.parse((ROOT / "tests/api/test_07_reader_images_tokens.py").read_text(encoding="utf-8"))
        manifest = next(
            node for node in reader_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_manifest"
        )
        self.assertTrue(any(
            isinstance(node, ast.Attribute) and node.attr == "get_json"
            for node in ast.walk(manifest)
        ))

    def test_catalog_taxonomy_writes_are_owned_and_granted(self):
        routes = json.loads((ROOT / 'contracts/ownership/routes.v1.json').read_text(encoding='utf-8'))['routes']
        contract = json.loads((ROOT / 'contracts/ownership/postgres-roles.v1.json').read_text(encoding='utf-8'))
        catalog = next(c for c in contract['capabilities'] if c['name'] == 'catalog_runtime')
        grants = {g['resource']: set(g['privileges']) for g in catalog['grants']}
        for resource, required in {
            'series_genres': {'select', 'insert', 'delete'},
            'series_tags': {'select', 'insert', 'delete'},
            'genres': {'select', 'insert', 'update'},
            'tags': {'select', 'insert', 'update'},
        }.items():
            self.assertTrue(required <= grants.get(resource, set()), (resource, grants.get(resource)))

        create = next(r for r in routes if r['method'] == 'POST' and r['path'] == '/api/catalog/series')
        update = next(r for r in routes if r['method'] == 'PUT' and r['path'] == '/api/catalog/series/{seriesID}')
        for route in (create, update):
            writes = {(w['resource'], a) for w in route['permitted_writes'] if w['kind'] == 'postgres' for a in w['actions']}
            for pair in {
                ('series_genres', 'insert'), ('series_genres', 'delete'),
                ('series_tags', 'insert'), ('series_tags', 'delete'),
                ('genres', 'insert'), ('genres', 'update'),
                ('tags', 'insert'), ('tags', 'update'),
            }:
                self.assertIn(pair, writes, (route['operation'], pair))

    def test_social_smart_library_view_is_readable_and_upgrade_reconciles_roles(self):
        contract = json.loads((ROOT / 'contracts/ownership/postgres-roles.v1.json').read_text(encoding='utf-8'))
        social = next(c for c in contract['capabilities'] if c['name'] == 'social_runtime')
        progress = next(c for c in contract['capabilities'] if c['name'] == 'progress_runtime')
        social_grants = {g['resource']: set(g['privileges']) for g in social['grants']}
        progress_grants = {g['resource']: set(g['privileges']) for g in progress['grants']}
        self.assertIn('select', social_grants.get('reading_state_v1', set()))
        self.assertIn('select', progress_grants.get('reading_state_v1', set()))
        self.assertIn('select', progress_grants.get('chapters', set()))
        deploy = (ROOT / 'scripts/hybrid/deploy.sh').read_text(encoding='utf-8')
        stateful = (ROOT / 'scripts/hybrid/stateful-up.sh').read_text(encoding='utf-8')
        self.assertIn('stateful-up.sh" core', deploy)
        self.assertIn('reconcile-postgres-roles.sh', stateful)

    def test_current_release_validator_runs_p12_5_contract(self):
        validator = (ROOT / 'scripts/validate-current-release.sh').read_text(encoding='utf-8')
        self.assertIn('tests.regression.test_p12_5_live_diagnostic_repairs', validator)

    def test_browser_regressions_match_auth_and_database_privacy_contracts(self):
        realtime = (ROOT / 'tests/browser/notification-realtime.spec.mjs').read_text(encoding='utf-8')
        admin_ui = (ROOT / 'tests/browser/admin-ui-smoke.spec.mjs').read_text(encoding='utf-8')
        self.assertIn('/api/auth/login', realtime)
        self.assertNotIn("getByText('Backup files / Filer namespace')", admin_ui)
        self.assertIn("getByText('Local recovery storage')", admin_ui)
        self.assertIn('Directory and filename details remain backend-only.', admin_ui)


if __name__ == '__main__':
    unittest.main()
