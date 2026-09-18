from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]

def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')

class AndroidReadingSourceAudit(unittest.TestCase):
    def test_reading_scope_is_origin_and_account_scoped_and_bounded(self):
        journal = text('android/app/src/main/java/com/mreader/android/core/repository/ReadingJournal.kt')
        repo = text('android/app/src/main/java/com/mreader/android/core/repository/ReadingRepository.kt')
        self.assertIn('data class ReadingScope(val origin: String, val accountId: String?)', journal)
        self.assertIn('const val MAX_PENDING = 500', journal)
        self.assertIn('const val MAX_BYTES = 5 * 1024 * 1024', journal)
        self.assertIn('const val CONFIRMED_TTL_MS = 7L * 24 * 60 * 60 * 1000', journal)
        self.assertIn('val scope = ReadingScope(origin, accountId)', repo)
        self.assertIn('delay(30_000L); flush()', repo)
        self.assertIn('delay(1_000L)', repo)

    def test_exact_payload_is_persisted_before_transport_and_auth_failure_suspends(self):
        repo = text('android/app/src/main/java/com/mreader/android/core/repository/ReadingRepository.kt')
        self.assertLess(repo.index('if (!save(account)) break'), repo.index('api.recordChapterOpen'))
        self.assertIn('if (error.status == 401 || error.status == 403)', repo)
        self.assertIn('account.suspended = true', repo)
        self.assertIn('fun retryTransport()', repo)

    def test_build_configured_origin_retires_old_preferences(self):
        config = text('android/app/src/main/java/com/mreader/android/core/settings/ServerConfigStore.kt')
        self.assertIn('BuildConfig.MREADER_DEFAULT_BASE_URL', config)
        self.assertIn('.remove(KEY_BASE_URL).remove(KEY_IMAGE_CDN_URL)', config)
        self.assertIn('fun current(): ServerConfig = ServerConfig(configuredOrigin, "")', config)
        self.assertNotRegex(config, r'getString\(KEY_BASE_URL|getString\(KEY_IMAGE_CDN_URL')

    def test_history_projection_comes_from_smart_library_not_progress_history(self):
        repo = text('android/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt')
        match = re.search(r'suspend fun history\([^}]+?\n\s*}\n', repo, re.S)
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertIn('smartLibrary(', body)
        self.assertIn('scope = "history"', body)
        self.assertNotIn('api.history(', body)
        all_android = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT/'android/app/src/main/java').rglob('*.kt'))
        self.assertNotIn('api.history(', all_android)

    def test_native_reader_uses_mobile_adapter_and_v4_only(self):
        repository = text('android/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt')
        screen = text('android/app/src/main/java/com/mreader/android/ui/screens/ReaderScreen.kt')
        self.assertIn('api.mobileReaderPage(', repository)
        self.assertIn('api.mobileReaderPage(', screen)
        self.assertIn('page.encodingVersion != 4', screen)
        self.assertIn('refreshChapterToken(', screen)
        # Direct protected-image fetch helpers must not return as a fallback.
        self.assertNotIn('fetchProtectedImage', repository)
        self.assertNotIn('fetchProtectedImage', screen)

    def test_webview_reader_stays_on_installed_origin(self):
        web = text('android/app/src/main/java/com/mreader/android/ui/screens/WebReaderScreen.kt')
        self.assertIn('repository.serverConfig().baseUrl', web)
        self.assertIn('if (!uri.host.equals(baseHost, ignoreCase = true)) return true', web)
        self.assertIn('repository.api.webViewCookies()', web)
        self.assertIn('setAcceptThirdPartyCookies(this, false)', web)
        self.assertIn('MIXED_CONTENT_NEVER_ALLOW', web)

    def test_logout_warns_and_clears_private_local_state(self):
        settings = text('android/app/src/main/java/com/mreader/android/ui/screens/SettingsScreen.kt')
        reading = text('android/app/src/main/java/com/mreader/android/core/repository/ReadingRepository.kt')
        local = text('android/app/src/main/java/com/mreader/android/core/repository/LocalProgressStore.kt')
        self.assertIn('repository.reading.hasPrivatePending()', settings)
        self.assertIn('Unsynced reading changes will be discarded', settings)
        self.assertIn('suspend fun discardPrivateForLogout()', reading)
        self.assertIn('disk.clearPrivate()', reading)
        self.assertIn('legacy.forEach', local)

    def test_protected_cache_identity_is_origin_scoped(self):
        repo = text('android/app/src/main/java/com/mreader/android/core/repository/MReaderRepository.kt')
        self.assertIn('return "${config.imageCdnUrl.ifBlank { config.baseUrl }}|${path.trimStart(\'/\')}"', repo)
        self.assertIn('assetStore.clear()', repo)
        self.assertIn('chapterTokens.clear()', repo)

if __name__ == '__main__':
    unittest.main()
