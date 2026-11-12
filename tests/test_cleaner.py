"""Tests for services/cleaner with a fake audio engine.

Real (tiny, silent) audio files are generated with ffmpeg so tag copying and
lyric masking run against real containers. The word list uses made-up words
("zorp", "blargh", "snorf") and the lyrics are invented lines.

Skipped unless ffmpeg and mutagen are available.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "cleaner"))

try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import ID3, TIT2, TPE1, USLT
    from mutagen.mp4 import MP4, MP4Cover

    from cleaner import lyrics, tags
    from cleaner.processor import Cleaner, Settings
    from cleaner.wordlist import WordList
except ImportError:  # pragma: no cover
    mutagen = None

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
CODECS = {".mp3": ["-c:a", "libmp3lame"], ".flac": ["-c:a", "flac"], ".m4a": ["-c:a", "aac"],
          ".wav": [], ".ogg": ["-c:a", "libvorbis"]}


def make_audio(path: Path, seconds: float = 0.3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo", "-t", str(seconds), *CODECS[path.suffix], str(path)],
                   check=True)
    return path


def tag_mp3(path: Path, title: str, artist: str, lyric: str | None = None) -> None:
    t = ID3()
    t.add(TIT2(encoding=3, text=title))
    t.add(TPE1(encoding=3, text=artist))
    if lyric:
        t.add(USLT(encoding=3, lang="eng", desc="", text=lyric))
    t.save(str(path))


def tag_flac(path: Path, title: str, artist: str, lyric: str | None = None, cover: bytes | None = None) -> None:
    f = FLAC(str(path))
    f["title"], f["artist"] = title, artist
    if lyric:
        f["LYRICS"] = lyric
    if cover:
        p = Picture()
        p.type, p.mime, p.data = 3, "image/jpeg", cover
        f.add_picture(p)
    f.save()


class FakeEngine:
    """Scripted transcripts keyed by file name; render writes a real (silent) file."""

    def __init__(self, transcripts: dict[str, list[dict]]):
        self.transcripts = transcripts
        self.calls = {"separate": 0, "transcribe": 0, "render": 0}
        self.lyrics_seen: dict[str, str | None] = {}

    def separate(self, audio, workdir):
        self.calls["separate"] += 1
        vocals, inst = Path(workdir) / "vocals.wav", Path(workdir) / "no_vocals.wav"
        vocals.write_text(audio.name)  # remember which track these stems belong to
        inst.write_text("")
        return vocals, inst

    def transcribe(self, vocals, lyrics_text):
        self.calls["transcribe"] += 1
        name = vocals.read_text()
        self.lyrics_seen[name] = lyrics_text
        return self.transcripts.get(name, [])

    def render(self, vocals, instrumentals, edits, out, fmt):
        self.calls["render"] += 1
        ext = {"mp3": ".mp3", "flac": ".flac", "ogg": ".ogg", "wav": ".wav"}[fmt]
        tmp = out.parent / f"render-tmp{ext}"
        make_audio(tmp)
        # Simulate music-profanity-filter's MP3 tagging (title + " (clean)").
        if fmt == "mp3":
            tag_mp3(tmp, "Something (clean)", "Someone")
        tmp.replace(out)


def words(*items):
    """words(("hello", 1.0), ("zorp", 2.0)) -> transcript dicts."""
    return [{"word": f" {w}", "start": t, "end": t + 0.4, "confidence": 0.9} for w, t in items]


@unittest.skipIf(mutagen is None, "mutagen not installed")
class WordListTests(unittest.TestCase):
    def setUp(self):
        self.wl = WordList.parse("# comment\nzorp\nblargh\n\nab\n")

    def test_parse_and_digest(self):
        self.assertEqual(self.wl.words, {"zorp", "blargh", "ab"})
        self.assertEqual(self.wl.digest, WordList(["ab", "blargh", "zorp"]).digest)
        self.assertNotEqual(self.wl.digest, WordList(["zorp"]).digest)

    def test_match(self):
        self.assertEqual(self.wl.match("Zorp!"), "zorp")
        self.assertEqual(self.wl.match("megazorpy"), "zorp")      # 4+ letters: contained
        self.assertEqual(self.wl.match("ab"), "ab")              # short: exact only
        self.assertIsNone(self.wl.match("about"))
        self.assertIsNone(self.wl.match("hello"))

    def test_check_text_and_mask(self):
        text = "Zorp the river,\nblargh and about"
        self.assertEqual(self.wl.check_text(text), ["zorp", "blargh"])
        self.assertEqual(self.wl.mask(text), "Z*** the river,\nb***** and about")

    def test_detect(self):
        edits = self.wl.detect(words(("hello", 1.0), ("zorps", 2.0)))
        self.assertEqual([(e.word, e.heard, e.start) for e in edits], [("zorp", "zorps", 2.0)])


@unittest.skipIf(mutagen is None or not HAVE_FFMPEG, "mutagen/ffmpeg not available")
class LyricsTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_strip_lrc(self):
        lrc = "[ar:Someone]\n[ti:Thing]\n[00:01.50]first line here\n[00:03.00]<00:03.10>second <00:03.40>line\n\n"
        self.assertEqual(lyrics.strip_lrc(lrc), "first line here\nsecond line")

    def test_sidecar_beats_embedded(self):
        song = make_audio(self.dir / "a.mp3")
        tag_mp3(song, "A", "B", lyric="embedded words")
        (self.dir / "a.lrc").write_text("[00:01.00]sidecar words")
        self.assertEqual(lyrics.find(song), ("sidecar words", "sidecar"))
        (self.dir / "a.lrc").unlink()
        self.assertEqual(lyrics.find(song), ("embedded words", "embedded"))

    def test_flac_embedded(self):
        song = make_audio(self.dir / "b.flac")
        tag_flac(song, "A", "B", lyric="flac words")
        self.assertEqual(lyrics.find(song), ("flac words", "embedded"))

    def test_none(self):
        self.assertEqual(lyrics.find(make_audio(self.dir / "c.mp3")), (None, None))


@unittest.skipIf(mutagen is None or not HAVE_FFMPEG, "mutagen/ffmpeg not available")
class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.src, self.out, self.data = self.root / "music", self.root / "music-clean", self.root / "data"
        self.wordfile = self.root / "words.txt"
        self.wordfile.write_text("zorp\nblargh\n")

        # 1. Has lyrics without listed words -> linked without touching the engine.
        self.calm = make_audio(self.src / "Calm Artist" / "calm.mp3")
        tag_mp3(self.calm, "Calm", "Calm Artist", lyric="a quiet line about rivers")
        # 2. No lyrics, transcript has no listed words -> linked after transcription.
        self.plain = make_audio(self.src / "Plain" / "plain.flac")
        tag_flac(self.plain, "Plain", "Plain Artist")
        # 3. Lyrics with a listed word; transcript hears it -> edited.
        self.rough = make_audio(self.src / "Rough" / "rough.mp3")
        tag_mp3(self.rough, "Rough Song", "Rough Artist", lyric="we zorp all night")
        (self.src / "Rough" / "cover.jpg").write_bytes(b"\xff\xd8fakejpeg")
        (self.src / "Rough" / "rough.lrc").write_text("[00:01.00]we zorp all night")

        self.engine = FakeEngine({
            "plain.flac": words(("snorf", 1.0), ("river", 1.5)),
            "rough.mp3": words(("we", 1.0), ("zorp", 1.4), ("all", 1.9), ("night", 2.2)),
        })

    def tearDown(self):
        shutil.rmtree(self.root)

    def cleaner(self, **kw):
        s = Settings(source=self.src, clean=self.out, data=self.data, wordlist_path=self.wordfile, **kw)
        return Cleaner(s, self.engine)

    def state(self):
        return json.loads((self.data / "state.json").read_text())["tracks"]

    def test_first_run(self):
        report = self.cleaner().run()
        self.assertEqual((report.scanned, report.linked, report.edited, report.failed), (3, 2, 1, 0))

        st = self.state()
        self.assertEqual(st["Calm Artist/calm.mp3"]["via"], "lyrics:embedded")
        self.assertEqual(st["Plain/plain.flac"]["via"], "transcript")
        self.assertEqual(st["Rough/rough.mp3"]["status"], "edited")
        self.assertEqual(st["Rough/rough.mp3"]["edits"][0]["word"], "zorp")

        # Only plain + rough were transcribed; the calm track was settled by its lyrics.
        self.assertEqual(self.engine.calls, {"separate": 2, "transcribe": 2, "render": 1})
        self.assertEqual(self.engine.lyrics_seen["rough.mp3"], "we zorp all night")   # sidecar used as context

        # Unchanged tracks are hardlinks to the originals (no extra space).
        self.assertEqual(os.stat(self.out / "Calm Artist" / "calm.mp3").st_ino, os.stat(self.calm).st_ino)
        # Edited track: a new file, original tags back (no " (clean)" suffix), lyrics masked.
        edited = self.out / "Rough" / "rough.mp3"
        self.assertNotEqual(os.stat(edited).st_ino, os.stat(self.rough).st_ino)
        id3 = ID3(str(edited))
        self.assertEqual(str(id3["TIT2"]), "Rough Song")
        self.assertEqual(str(id3["TPE1"]), "Rough Artist")
        self.assertEqual(str(id3.getall("USLT")[0].text), "we z*** all night")
        # Sidecars: lyrics masked, cover linked.
        self.assertEqual((self.out / "Rough" / "rough.lrc").read_text(), "[00:01.00]we z*** all night")
        self.assertTrue((self.out / "Rough" / "cover.jpg").exists())
        # Originals untouched.
        self.assertEqual(str(ID3(str(self.rough)).getall("USLT")[0].text), "we zorp all night")
        # Review log.
        rows = list(csv.DictReader((self.data / "review.csv").open()))
        self.assertEqual([(r["path"], r["word"], r["start"], r["title"]) for r in rows],
                         [("Rough/rough.mp3", "zorp", "1.40", "Rough Song")])

    def test_second_run_does_nothing(self):
        self.cleaner().run()
        before = dict(self.engine.calls)
        report = self.cleaner().run()
        self.assertEqual((report.skipped, report.linked, report.edited), (3, 0, 0))
        self.assertEqual(self.engine.calls, before)

    def test_word_list_change_reuses_transcripts(self):
        self.cleaner().run()
        before = dict(self.engine.calls)
        self.wordfile.write_text("zorp\nblargh\nsnorf\n")    # now the plain track needs an edit
        report = self.cleaner().run()
        self.assertEqual(report.edited, 1)
        self.assertEqual(self.engine.calls["transcribe"], before["transcribe"])   # cached transcript
        self.assertEqual(self.engine.calls["separate"], before["separate"] + 1)   # stems for the new edit
        self.assertEqual(self.state()["Plain/plain.flac"]["status"], "edited")
        f = FLAC(str(self.out / "Plain" / "plain.flac"))
        self.assertEqual(f["title"], ["Plain"])
        # The rough track's edits didn't change -> not re-rendered.
        self.assertEqual(self.engine.calls["render"], before["render"] + 1)

    def test_removing_a_word_relinks(self):
        self.cleaner().run()
        self.wordfile.write_text("blargh\n")
        report = self.cleaner().run()
        self.assertEqual(self.state()["Rough/rough.mp3"]["status"], "linked")
        self.assertEqual(os.stat(self.out / "Rough" / "rough.mp3").st_ino, os.stat(self.rough).st_ino)
        self.assertEqual((self.out / "Rough" / "rough.lrc").read_text(), "[00:01.00]we zorp all night")
        self.assertGreaterEqual(report.linked, 1)

    def test_changed_source_is_reprocessed(self):
        self.cleaner().run()
        before = dict(self.engine.calls)
        time.sleep(0.01)
        tag_mp3(self.rough, "Rough Song (Remaster)", "Rough Artist", lyric="we zorp all night")
        self.cleaner().run()
        self.assertEqual(self.engine.calls["transcribe"], before["transcribe"] + 1)
        self.assertEqual(str(ID3(str(self.out / "Rough" / "rough.mp3"))["TIT2"]), "Rough Song (Remaster)")

    def test_prune(self):
        self.cleaner().run()
        shutil.rmtree(self.src / "Rough")
        report = self.cleaner().run()
        self.assertFalse((self.out / "Rough" / "rough.mp3").exists())
        self.assertFalse((self.out / "Rough" / "cover.jpg").exists())
        self.assertEqual(report.pruned, 3)   # track + cover + lrc

    def test_dry_run_writes_nothing(self):
        report = self.cleaner(dry_run=True).run()
        self.assertEqual(report.would_edit, ["Rough/rough.mp3"])
        self.assertFalse(self.out.exists() and any(self.out.rglob("*")))
        self.assertTrue((self.data / "review-dry-run.csv").exists())

    def test_m4a_becomes_flac_with_tags_and_cover(self):
        m4a = make_audio(self.src / "Mp4" / "track.m4a")
        f = MP4(str(m4a))
        f["\xa9nam"], f["\xa9ART"], f["\xa9lyr"] = ["Mp4 Song"], ["Mp4 Artist"], ["blargh in the lyrics"]
        f["covr"] = [MP4Cover(b"\xff\xd8cover", imageformat=MP4Cover.FORMAT_JPEG)]
        f.save()
        self.engine.transcripts["track.m4a"] = words(("blargh", 0.1))
        self.cleaner().run()
        self.assertFalse((self.out / "Mp4" / "track.m4a").exists())
        out = FLAC(str(self.out / "Mp4" / "track.flac"))
        self.assertEqual((out["title"], out["artist"]), (["Mp4 Song"], ["Mp4 Artist"]))
        self.assertEqual(out["LYRICS"], ["b***** in the lyrics"])
        self.assertEqual(out.pictures[0].data, b"\xff\xd8cover")

    def test_failure_is_recorded_and_retried(self):
        self.engine.transcripts = None   # transcribe() will raise
        report = self.cleaner().run()
        self.assertEqual(report.failed, 2)
        self.assertEqual(self.state()["Rough/rough.mp3"]["status"], "failed")
        self.engine.transcripts = {"rough.mp3": words(("zorp", 1.0))}
        report = self.cleaner().run()
        self.assertEqual(report.failed, 0)
        self.assertEqual(self.state()["Rough/rough.mp3"]["status"], "edited")

    def test_refuses_nested_paths(self):
        with self.assertRaises(ValueError):
            Cleaner(Settings(source=self.src, clean=self.src / "clean", data=self.data,
                             wordlist_path=self.wordfile), self.engine)


if __name__ == "__main__":
    unittest.main()
