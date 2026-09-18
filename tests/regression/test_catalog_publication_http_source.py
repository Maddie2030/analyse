from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services/catalog_go/internal/httpapi/api.go"


class CatalogPublicationHTTPSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = API.read_text()

    def test_private_publication_route_is_registered(self):
        self.assertIn('r.Post("/internal/v1/catalog/publications", a.commitPublication)', self.source)

    def test_handler_decodes_command_and_requires_retained_actor_match(self):
        self.assertIn('func (a *API) commitPublication(', self.source)
        self.assertIn('var command model.PublicationCommand', self.source)
        self.assertIn('X-MReader-Requesting-Actor-ID', self.source)
        self.assertIn('command.ActorID', self.source)
        self.assertIn('a.store.CommitPublication', self.source)

    def test_handler_respects_catalog_write_mode(self):
        handler = self.source[self.source.index('func (a *API) commitPublication('):]
        handler = handler[:handler.index('\nfunc ', 1)]
        self.assertIn('a.requireInternalWrite(w, r)', handler)
        guard = self.source[self.source.index('func (a *API) requireInternalWrite('):]
        guard = guard[:guard.index('\nfunc ', 1)]
        self.assertIn('a.enableWrites', guard)
        self.assertIn('http.StatusServiceUnavailable', guard)

    def test_handler_maps_publication_domain_errors_to_stable_codes(self):
        for symbol in (
            'store.ErrIdempotencyConflict',
            'store.ErrStaleCatalogRevision',
            'store.ErrMediaEvidenceMismatch',
            'store.ErrPublicationActorUnauthorized',
            'store.ErrStaleIngestionSourceRevision',
            'store.ErrStaleIngestionGeneration',
            'store.ErrIngestionCancelled',
            'store.ErrIngestionNotRunning',
        ):
            self.assertIn(symbol, self.source)
        self.assertIn('"code"', self.source)
        self.assertIn('a.invalidateChapterCaches(r)', self.source)


if __name__ == '__main__':
    unittest.main()
