"""scripts/sync-ha-config.sh against a local folder standing in for the Samba 'config' share."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync-ha-config.sh"
SRC = ROOT / "deploy" / "homeassistant"


@unittest.skipIf(shutil.which("bash") is None or shutil.which("tar") is None, "bash/tar not available")
class SyncScript(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp())
        # An existing HA config with unrelated files that must survive.
        (self.target / "configuration.yaml").write_text("default_config:\n")
        (self.target / "secrets.yaml").write_text("db_password: hunter2")   # no trailing newline
        (self.target / "custom_sentences" / "en").mkdir(parents=True)
        (self.target / "custom_sentences" / "en" / "mine.yaml").write_text("language: en\n")

    def tearDown(self):
        shutil.rmtree(self.target)

    def run_sync(self, *args):
        return subprocess.run(["bash", str(SCRIPT), str(self.target), *args],
                              capture_output=True, text=True)

    def test_dry_run_changes_nothing(self):
        r = self.run_sync("--dry-run")
        self.assertIn("packages/music_voice.yaml", r.stdout)
        self.assertFalse((self.target / "packages").exists())

    def test_copies_files_and_reports_missing_setup(self):
        r = self.run_sync()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for rel in ["packages/music_voice.yaml", "custom_sentences/en/music.yaml",
                    "custom_templates/music_voice.jinja"]:
            self.assertEqual((self.target / rel).read_bytes(), (SRC / rel).read_bytes(), rel)
        self.assertFalse((self.target / "ai_prompt.txt").exists())          # not HA config
        self.assertTrue((self.target / "custom_sentences" / "en" / "mine.yaml").exists())  # untouched
        self.assertIn("packages: !include_dir_named packages", r.stdout)
        self.assertIn("music_default_player", r.stdout)
        self.assertEqual((self.target / "secrets.yaml").read_text(), "db_password: hunter2")

    def test_add_secrets_then_clean_run(self):
        (self.target / "configuration.yaml").write_text(
            "default_config:\nhomeassistant:\n  packages: !include_dir_named packages\n")
        r = self.run_sync("--add-secrets")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        secrets = (self.target / "secrets.yaml").read_text()
        self.assertTrue(secrets.startswith("db_password: hunter2\n"))
        for key in ["music_default_player:", "music_allow_streaming:", "music_speakers:"]:
            self.assertEqual(secrets.count(key), 1)
        # Second run: everything in place, nothing appended again.
        r = self.run_sync("--add-secrets")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.target / "secrets.yaml").read_text(), secrets)

    def test_secrets_are_valid_yaml_for_the_package(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed")
        self.run_sync("--add-secrets")
        secrets = yaml.safe_load((self.target / "secrets.yaml").read_text())
        self.assertIsInstance(secrets["music_default_player"], str)
        self.assertIs(secrets["music_allow_streaming"], True)
        self.assertIsInstance(secrets["music_speakers"], list)

    def test_missing_target(self):
        r = subprocess.run(["bash", str(SCRIPT), str(self.target / "nope")], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mount the Samba", r.stderr)


if __name__ == "__main__":
    unittest.main()
