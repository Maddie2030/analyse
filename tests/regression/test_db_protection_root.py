import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts/env/db-protection-root.sh"
CLI = ROOT / "scripts/env/resolve-db-protection-root.sh"


class RootTests(unittest.TestCase):
    def normalize(self, platform, home, profile="", configured=""):
        return subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"\ndbp_normalize_root "$2" "$3" "$4" "$5"',
                "dbp-test",
                str(MODULE),
                platform,
                home,
                profile,
                configured,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_linux_home_with_spaces(self):
        result = self.normalize("linux", "/home/Reader One")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "/home/Reader One/.mreader/database-protection"
        )

    def test_windows_blank_root_uses_fixed_dedicated_directory(self):
        result = self.normalize("windows", "/weird/git-bash/home", "not-a-drive-path")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "C:/mreader/database-protection"
        )

    def test_windows_profile_not_git_bash_home(self):
        result = self.normalize("windows", "/c/git-bash-home", r"C:\Users\Reader One")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "C:/mreader/database-protection"
        )

    def test_existing_path_is_not_rederived(self):
        result = self.normalize(
            "linux", "/home/new-user", configured="/srv/mreader recovery/"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/srv/mreader recovery")

    def test_quoted_literal_is_supported(self):
        result = self.normalize("linux", "/home/a", configured="'/srv/reader backups'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "/srv/reader backups")

    def test_unsafe_or_ambiguous_paths_fail(self):
        values = [
            "relative/backups",
            "/",
            "/home/a",
            "/srv/../etc",
            "/srv/./data",
            "/srv//data",
            "$HOME/backups",
            "$(touch /tmp/no)",
            "/srv/a#b",
            "/srv/a\nb",
            "/srv/a\tb",
            "/srv/a`id`",
            r"/srv/a\b",
            "https://example/backups",
        ]
        for value in values:
            with self.subTest(value=value):
                result = self.normalize("linux", "/home/a", configured=value)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_windows_git_bash_profile_is_canonicalized_to_drive_path(self):
        result = self.normalize("windows", "/c/Users/Reader One", "/c/Users/Reader One")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "C:/mreader/database-protection"
        )

    def test_windows_git_bash_home_is_used_when_userprofile_is_missing(self):
        result = self.normalize("windows", "/c/Users/Reader One", "")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "C:/mreader/database-protection"
        )

    def test_windows_cygwin_profile_is_canonicalized_to_drive_path(self):
        result = self.normalize(
            "windows", "/cygdrive/c/Users/Reader One", "/cygdrive/c/Users/Reader One"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(), "C:/mreader/database-protection"
        )

    def test_windows_cli_recovers_profile_from_cmd_when_env_profile_is_missing(self):
        with tempfile.TemporaryDirectory(prefix="mreader-win-profile-") as directory:
            fixture = Path(directory)
            env_file = fixture / ".env"
            env_file.write_text("MREADER_DB_PROTECTION_ROOT=\n")
            binary = fixture / "bin"
            binary.mkdir()
            (binary / "uname").write_text(
                "#!/usr/bin/env bash\nprintf '%s\n' 'MINGW64_NT-10.0-19045'\n"
            )
            (binary / "cmd.exe").write_text(
                "#!/usr/bin/env bash\n"
                "[[ \"${MSYS_NO_PATHCONV:-}\" == 1 ]] || { echo missing-msys-pathconv-guard >&2; exit 9; }\n"
                "printf '%s\r\n' 'C:\\Users\\Reader One'\n"
            )
            for tool in (binary / "uname", binary / "cmd.exe"):
                tool.chmod(0o755)
            child_env = dict(
                os.environ,
                PATH=f"{binary}:{os.environ['PATH']}",
                HOME="/home/Reader One",
                USERPROFILE="",
                MREADER_DB_PROTECTION_ROOT="",
            )
            result = subprocess.run(
                ["bash", str(CLI), str(env_file)],
                env=child_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                "C:/mreader/database-protection",
            )
            self.assertIn(
                "MREADER_DB_PROTECTION_ROOT=C:/mreader/database-protection",
                env_file.read_text(),
            )

    def test_windows_requires_absolute_drive_for_configured_paths(self):
        for profile, configured in [
            (r"C:\Users\a", "C:/"),
            (r"C:\Users\a", "//server/share"),
        ]:
            with self.subTest(profile=profile, configured=configured):
                result = self.normalize("windows", "/c/a", profile, configured)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_windows_whole_home_is_rejected_case_insensitively(self):
        result = self.normalize(
            "windows", "/c/git-home", r"c:\Users\Reader", "C:/users/reader"
        )
        self.assertEqual(result.returncode, 2, result.stderr)


class PersistenceTests(unittest.TestCase):
    def resolve(self, env_file, home="/home/Reader One", override=""):
        script = (
            'source "$1/scripts/env/env-lib.sh"\n'
            'source "$1/scripts/env/db-protection-root.sh"\n'
            'dbp_resolve_env "$2" linux "$3" "" "$4"'
        )
        return subprocess.run(
            [
                "bash",
                "-c",
                script,
                "dbp-test",
                str(ROOT),
                str(env_file),
                home,
                override,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_persists_once_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "TOKEN_SECRET=fixture-not-a-real-secret\n"
                "MREADER_DB_PROTECTION_ROOT=\n"
            )
            first = self.resolve(path)
            self.assertEqual(first.returncode, 0, first.stderr)
            saved = path.read_bytes()
            second = self.resolve(path, home="/home/different")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout, first.stdout)
            self.assertEqual(path.read_bytes(), saved)
            self.assertIn(b"TOKEN_SECRET=fixture-not-a-real-secret\n", saved)
            self.assertEqual(saved.count(b"MREADER_DB_PROTECTION_ROOT="), 1)

    def test_override_cannot_silently_replace_existing_root(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = b"MREADER_DB_PROTECTION_ROOT=/srv/reader-backups\n"
            path.write_bytes(original)
            result = self.resolve(path, override="/srv/other-backups")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_config_is_not_replaced_with_a_default(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = b"MREADER_DB_PROTECTION_ROOT=relative/unsafe\n"
            path.write_bytes(original)
            result = self.resolve(path)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_duplicate_roots_require_explicit_resolution(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            original = (
                b"MREADER_DB_PROTECTION_ROOT=/srv/first\n"
                b"MREADER_DB_PROTECTION_ROOT=/srv/second\n"
            )
            path.write_bytes(original)
            result = self.resolve(path)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_cli_uses_explicit_temp_root_without_creating_directories(self):
        with tempfile.TemporaryDirectory(prefix="mreader-root-") as directory:
            path = Path(directory) / ".env"
            recovery = Path(directory) / "recovery with spaces"
            path.write_text("TOKEN_SECRET=fixture\n")
            child_env = dict(os.environ, MREADER_DB_PROTECTION_ROOT=str(recovery))
            result = subprocess.run(
                ["bash", str(CLI), str(path)],
                env=child_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(recovery))
            self.assertFalse(recovery.exists())

    def test_startup_entry_points_resolve_before_stateful_mutation(self):
        for entry in [
            "scripts/bootstrap.sh",
            "scripts/hybrid-up.sh",
            "scripts/hybrid/stateful-up.sh",
        ]:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory(
                prefix="mreader-startup-"
            ) as directory:
                fixture = Path(directory)
                shutil.copytree(ROOT / "scripts", fixture / "scripts")
                shutil.copy(ROOT / ".env.example", fixture / ".env.example")
                (fixture / ".env").write_text(
                    "TOKEN_SECRET=fixture\n"
                    "MREADER_DB_PROTECTION_ROOT=relative/unsafe\n"
                )
                binary = fixture / "bin"
                binary.mkdir()
                marker = fixture / "resource-work.log"
                docker = binary / "docker"
                docker.write_text(
                    "#!/usr/bin/env bash\n"
                    'if [[ "$1" == info || ( "$1" == compose && "${2:-}" == version ) ]]; then exit 0; fi\n'
                    'printf "%s\\n" "$*" >> "$DBP_TEST_RESOURCE_LOG"\nexit 77\n'
                )
                docker.chmod(0o755)
                kubectl = binary / "kubectl"
                kubectl.write_text("#!/usr/bin/env bash\nexit 77\n")
                kubectl.chmod(0o755)
                child_env = dict(
                    os.environ,
                    PATH=f"{binary}:{os.environ['PATH']}",
                    MREADER_DB_PROTECTION_ROOT="",
                    DBP_TEST_RESOURCE_LOG=str(marker),
                )
                result = subprocess.run(
                    ["bash", str(fixture / entry)],
                    cwd=fixture,
                    env=child_env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("absolute Linux recovery path", result.stderr)
                self.assertFalse(marker.exists(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
