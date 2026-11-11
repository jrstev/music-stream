"""Check the Assist custom sentences with hassil, Home Assistant's own matcher.

Skipped unless `hassil` and `pyyaml` are installed:
    pip install hassil pyyaml
"""
import unittest
from pathlib import Path

try:
    import yaml
    from hassil import Intents, recognize_best
    from hassil.intents import TextSlotList
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant"
SENTENCES = ROOT / "custom_sentences" / "en" / "music.yaml"
PACKAGE = ROOT / "packages" / "music_voice.yaml"


@unittest.skipIf(yaml is None, "hassil/pyyaml not installed")
class VoiceSentences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.intents = Intents.from_dict(yaml.safe_load(SENTENCES.read_text()))
        # Home Assistant supplies {area} at runtime from your configured areas.
        cls.slot_lists = {"area": TextSlotList.from_strings(["kitchen", "living room", "office"])}

    def match(self, text):
        # Same call Home Assistant's default conversation agent makes.
        result = recognize_best(text, self.intents, slot_lists=self.slot_lists,
                                best_metadata_key="hass_custom_sentence", best_slot_name="name")
        self.assertIsNotNone(result, f"no match for {text!r}")
        self.assertEqual(result.intent.name, "PlayLocalMusic")
        return {k: str(v.value).strip() for k, v in result.entities.items()}

    def check(self, text, **expected):
        got = self.match(text)
        for key, value in expected.items():
            self.assertEqual(got.get(key), value, f"{text!r}: {key} -> {got}")
        for key in {"artist", "area", "radio"} - expected.keys():
            self.assertNotIn(key, got, f"{text!r}: unexpected {key} -> {got}")

    def test_track_by_artist(self):
        self.check("play teardrop by massive attack",
                   query="teardrop", artist="massive attack", media_type="track")

    def test_track_by_artist_in_area(self):
        self.check("play teardrop by massive attack in the living room",
                   query="teardrop", artist="massive attack", area="living room", media_type="track")

    def test_song_called_keeps_by_in_title(self):
        self.check("play the song called stand by me in the kitchen",
                   query="stand by me", area="kitchen", media_type="track")

    def test_by_in_title_is_split_then_retried_by_script(self):
        # Ambiguous on purpose: the intent_script retries "stand by me" as a
        # title when "stand" by "me" isn't in the library.
        self.check("play stand by me", query="stand", artist="me", media_type="track")

    def test_song_with_artist(self):
        # hassil prefers the single-wildcard template; the intent_script then
        # splits "paranoid android by radiohead" (see test_music_voice_templates).
        self.check("play the song paranoid android by radiohead",
                   query="paranoid android by radiohead", media_type="track")

    def test_album(self):
        self.check("play the album kid a by radiohead on the office",
                   query="kid a by radiohead", area="office", media_type="album")

    def test_album_without_artist(self):
        self.check("play album in rainbows", query="in rainbows", media_type="album")

    def test_artist(self):
        self.check("play music by boards of canada in the kitchen",
                   query="boards of canada", area="kitchen", media_type="artist")
        self.check("play the band radiohead", query="radiohead", media_type="artist")

    def test_playlist(self):
        self.check("play my chill playlist", query="chill", media_type="playlist")
        self.check("play playlist sunday morning in the kitchen",
                   query="sunday morning", area="kitchen", media_type="playlist")

    def test_radio_mode(self):
        self.check("play something like bonobo", query="bonobo", media_type="artist", radio="true")

    def test_package_is_valid_yaml(self):
        pkg = yaml.safe_load(PACKAGE.read_text())
        self.assertIn("PlayLocalMusic", pkg["intent_script"])


if __name__ == "__main__":
    unittest.main()
