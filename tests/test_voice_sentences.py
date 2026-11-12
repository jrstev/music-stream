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

    def match(self, text, intent="PlayLocalMusic"):
        # Same call Home Assistant's default conversation agent makes.
        result = recognize_best(text, self.intents, slot_lists=self.slot_lists,
                                best_metadata_key="hass_custom_sentence", best_slot_name="name")
        self.assertIsNotNone(result, f"no match for {text!r}")
        self.assertEqual(result.intent.name, intent, text)
        return {k: str(v.value).strip() for k, v in result.entities.items()}

    def check(self, text, **expected):
        got = self.match(text)
        for key, value in expected.items():
            self.assertEqual(got.get(key), value, f"{text!r}: {key} -> {got}")
        for key in {"artist", "area", "radio", "source"} - expected.keys():
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

    # --- source: library only / straight to Spotify ---------------------------
    def test_from_my_library(self):
        self.check("play teardrop by massive attack from my library",
                   query="teardrop", artist="massive attack", media_type="track", source="library")

    def test_on_spotify(self):
        self.check("play nightcall by kavinsky on spotify",
                   query="nightcall", artist="kavinsky", media_type="track", source="streaming")

    def test_area_and_source(self):
        self.check("play the album kid a in the kitchen from spotify",
                   query="kid a", area="kitchen", media_type="album", source="streaming")

    def test_spotify_not_mistaken_for_area(self):
        self.check("play music by radiohead on spotify",
                   query="radiohead", media_type="artist", source="streaming")

    # --- blocklist --------------------------------------------------------------
    def test_block_current_song(self):
        for text in ["block this song", "never play this song again", "add this track to my blocklist"]:
            self.match(text, intent="BlockCurrentSong")
        self.assertEqual(self.match("block this song in the office", intent="BlockCurrentSong")["area"],
                         "office")

    def test_block_by_name(self):
        # One wildcard beats two, so "X by Y" arrives whole; music_block_song splits it.
        got = self.match("block wonderwall by oasis", intent="BlockSong")
        self.assertEqual((got["query"], got["media_type"]), ("wonderwall by oasis", "any"))
        got = self.match("block the artist nickelback", intent="BlockSong")
        self.assertEqual((got["query"], got["media_type"]), ("nickelback", "artist"))
        got = self.match("block nickelback", intent="BlockSong")
        self.assertEqual((got["query"], got["media_type"]), ("nickelback", "any"))
        got = self.match("add mr brightside to my blocklist", intent="BlockSong")
        self.assertEqual(got["query"], "mr brightside")
        got = self.match("never play baby shark again", intent="BlockSong")
        self.assertEqual(got["query"], "baby shark")

    def test_current_song_phrases_still_win(self):
        # Literal phrases beat the "block {query}" wildcard templates.
        for text in ["block this song", "never play this song again", "add this song to my blocklist"]:
            self.match(text, intent="BlockCurrentSong")

    def test_unblock(self):
        got = self.match("unblock wonderwall by oasis", intent="UnblockSong")
        self.assertEqual((got["query"], got["media_type"]), ("wonderwall by oasis", "any"))
        got = self.match("unblock the band nickelback", intent="UnblockSong")
        self.assertEqual((got["query"], got["media_type"]), ("nickelback", "artist"))
        got = self.match("remove baby shark from the blocked list", intent="UnblockSong")
        self.assertEqual((got["query"], got["media_type"]), ("baby shark", "any"))

    def test_package_is_valid_yaml(self):
        pkg = yaml.safe_load(PACKAGE.read_text())
        self.assertEqual(set(pkg["intent_script"]),
                         {"PlayLocalMusic", "BlockCurrentSong", "BlockSong", "UnblockSong"})
        self.assertEqual(set(pkg["script"]),
                         {"music_play_from_library", "music_library_search", "music_block_current_song",
                          "music_block_song", "music_unblock_song"})


if __name__ == "__main__":
    unittest.main()
