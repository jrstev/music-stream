import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gen_voice_routines as g  # noqa: E402

KITCHEN = g.Speaker("kitchen", "media_player.kitchen")
LIVING = g.Speaker("living room", "media_player.living_room")


class ParsePlaylists(unittest.TestCase):
    def test_ok(self):
        payload = {"subsonic-response": {"status": "ok", "playlists": {"playlist": [
            {"id": "1", "name": "Jazz"}, {"id": "2", "name": "Chill/Focus #2"}]}}}
        self.assertEqual(g.parse_playlists(payload), ["Jazz", "Chill/Focus #2"])

    def test_error(self):
        payload = {"subsonic-response": {"status": "failed", "error": {"code": 40, "message": "Wrong creds"}}}
        with self.assertRaisesRegex(RuntimeError, "Wrong creds"):
            g.parse_playlists(payload)


class BuildCommands(unittest.TestCase):
    def test_single_speaker(self):
        cmds = g.build_commands([g.MediaItem("Chill/Focus #2", "playlist")], [KITCHEN], "kitchen")
        self.assertEqual([c.phrase for c in cmds], ["play my chill focus 2 playlist"])
        self.assertEqual(cmds[0].script_id, "music_playlist_chill_focus_2_kitchen")

    def test_multi_room_default_shares_script(self):
        cmds = g.build_commands([g.MediaItem("Jazz", "playlist")], [KITCHEN, LIVING], "kitchen")
        phrases = {c.phrase: c.script_id for c in cmds}
        self.assertEqual(phrases, {
            "play my jazz playlist in the kitchen": "music_playlist_jazz_kitchen",
            "play my jazz playlist": "music_playlist_jazz_kitchen",
            "play my jazz playlist in the living room": "music_playlist_jazz_living_room",
        })

    def test_slug_collision(self):
        items = [g.MediaItem("Rock'n", "playlist"), g.MediaItem("Rock n", "playlist")]
        ids = {c.script_id for c in g.build_commands(items, [KITCHEN], "kitchen")}
        self.assertEqual(ids, {"music_playlist_rock_n_kitchen", "music_playlist_rock_n_kitchen_2"})

    def test_identical_spoken_phrase_is_deduped(self):
        items = [g.MediaItem("Rock!", "playlist"), g.MediaItem("rock", "playlist")]
        cmds = g.build_commands(items, [KITCHEN], "kitchen")
        self.assertEqual([c.phrase for c in cmds], ["play my rock playlist"])


class EndToEnd(unittest.TestCase):
    def test_cli_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            pj = Path(d) / "p.json"
            pj.write_text(json.dumps({"subsonic-response": {"status": "ok",
                                      "playlists": {"playlist": [{"name": 'Say "Hi"'}]}}}))
            rc = g.main(["--speaker", "kitchen=media_player.kitchen", "--playlists-json", str(pj),
                         "--artist", "Boards of Canada", "--out", d])
            self.assertEqual(rc, 0)
            ha = (Path(d) / "ha_scripts.yaml").read_text()
            gh = (Path(d) / "google_home_routines.yaml").read_text()
            self.assertIn('media_id: "Say \\"Hi\\""', ha)
            self.assertIn("media_type: artist", ha)
            self.assertIn('is: "play my boards of canada artist"', gh)
            self.assertEqual(gh.count("assistant.event.OkGoogle"), 2)
            try:  # validate YAML if PyYAML happens to be installed
                import yaml
            except ImportError:
                return
            self.assertEqual(len(yaml.safe_load(ha)), 2)
            self.assertEqual(len(yaml.safe_load(gh)["automations"]), 2)


if __name__ == "__main__":
    unittest.main()
