"""Mirror a music library into a "clean" copy with listed words muted.

For each audio file under SOURCE:
  1. Up to date (same size/mtime, same word list, output present)? Skip.
  2. Reference lyrics (sidecar .lrc/.txt, embedded tags, optional Genius).
     If lyrics exist, contain no listed word and TRUST_LYRICS is on: link unchanged.
  3. Transcribe the vocals (Demucs + Whisper, lyrics as context), cached per track,
     so editing the word list later only re-runs detection.
  4. No listed words heard: link the original unchanged (hardlink: no extra space).
  5. Otherwise mute them in the vocal stem, remix, write the clean file, copy the
     original tags back, mask lyric tags, and log each edit to review.csv.
Other files (cover art, .lrc, ...) are linked; .lrc/.txt lyrics are masked when needed.
The source tree is only ever read.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import lyrics as lyrics_mod
from . import tags as tags_mod
from .engine import Engine
from .wordlist import Edit, WordList

log = logging.getLogger("cleaner")

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".aiff", ".aif"}
# Formats the remix step can write back as-is; everything else becomes FLAC (lossless).
NATIVE_OUT = {".mp3": "mp3", ".flac": "flac", ".ogg": "ogg", ".wav": "wav"}
LYRIC_SIDECARS = {".lrc", ".txt"}
REVIEW_FIELDS = ["time", "path", "artist", "title", "start", "end", "word", "heard", "confidence", "lyrics"]


@dataclass
class Settings:
    source: Path
    clean: Path
    data: Path
    wordlist_path: Path | None = None
    link_mode: str = "hardlink"        # hardlink | copy | symlink
    trust_lyrics: bool = True          # lyrics without listed words => skip audio analysis
    genius_token: str | None = None
    prune: bool = True                 # remove clean files whose original is gone
    dry_run: bool = False              # detect and report only; write nothing to CLEAN


@dataclass
class Report:
    scanned: int = 0
    skipped: int = 0
    linked: int = 0
    edited: int = 0
    failed: int = 0
    pruned: int = 0
    would_edit: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _out_suffix(src: Path) -> str:
    return src.suffix.lower() if src.suffix.lower() in NATIVE_OUT else ".flac"


class Cleaner:
    def __init__(self, settings: Settings, engine: Engine, words: WordList | None = None):
        self.s = settings
        self.engine = engine
        self.words = words or WordList.load(settings.wordlist_path)
        self._check_paths()
        self.s.data.mkdir(parents=True, exist_ok=True)
        (self.s.data / "transcripts").mkdir(exist_ok=True)
        self.state_path = self.s.data / "state.json"
        self.state: dict = self._load_state()

    # ---- setup ------------------------------------------------------------------
    def _check_paths(self) -> None:
        src, dst = self.s.source.resolve(), self.s.clean.resolve()
        if src == dst or src in dst.parents or dst in src.parents:
            raise ValueError(f"SOURCE ({src}) and CLEAN ({dst}) must not contain each other")
        if not src.is_dir():
            raise ValueError(f"SOURCE is not a directory: {src}")

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                log.warning("state.json unreadable; starting fresh")
        return {"tracks": {}, "files": {}}

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True))
        tmp.replace(self.state_path)

    # ---- run ---------------------------------------------------------------------
    def run(self) -> Report:
        report = Report()
        seen_tracks, seen_files = set(), set()
        for path in sorted(self.s.source.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            rel = path.relative_to(self.s.source).as_posix()
            if path.suffix.lower() in AUDIO_EXTS:
                seen_tracks.add(rel)
                report.scanned += 1
                try:
                    self._track(path, rel, report)
                except Exception as exc:  # keep going; record and retry next run
                    log.exception("failed: %s", rel)
                    report.failed += 1
                    report.errors[rel] = str(exc)
                    self.state["tracks"][rel] = {**self._key(path), "status": "failed", "error": str(exc)}
                self._save_state()
            else:
                seen_files.add(rel)
                if not self.s.dry_run:
                    self._other_file(path, rel)
        if self.s.prune and not self.s.dry_run:
            report.pruned = self._prune(seen_tracks, seen_files)
        self._save_state()
        (self.s.data / "last_run.json").write_text(json.dumps(
            {"finished": datetime.now(timezone.utc).isoformat(), "wordlist": self.words.digest,
             **report.as_dict()}, indent=1))
        return report

    # ---- one track ------------------------------------------------------------------
    @staticmethod
    def _key(path: Path) -> dict:
        st = path.stat()
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}

    def _transcript_path(self, rel: str) -> Path:
        return self.s.data / "transcripts" / (hashlib.sha1(rel.encode()).hexdigest() + ".json")

    def _track(self, path: Path, rel: str, report: Report) -> None:
        key = self._key(path)
        prev = self.state["tracks"].get(rel, {})
        same_source = prev.get("size") == key["size"] and prev.get("mtime_ns") == key["mtime_ns"]
        prev_out = self.s.clean / prev["out"] if prev.get("out") else None
        if (same_source and prev.get("wordlist") == self.words.digest
                and prev.get("status") in ("edited", "linked") and prev_out and prev_out.exists()):
            report.skipped += 1
            return

        text, lyrics_src = lyrics_mod.find(path, self.s.genius_token)

        # Cached transcription for this exact file?
        words = None
        tpath = self._transcript_path(rel)
        if tpath.exists():
            cached = json.loads(tpath.read_text())
            if cached.get("size") == key["size"] and cached.get("mtime_ns") == key["mtime_ns"]:
                words = cached["words"]

        stems_dir = None
        try:
            if words is None:
                if text and self.s.trust_lyrics and not self.words.check_text(text):
                    self._finish_linked(path, rel, key, report, via=f"lyrics:{lyrics_src}")
                    return
                stems_dir = Path(tempfile.mkdtemp(prefix="cleaner_", dir=self.s.data))
                vocals, instrumentals = self.engine.separate(path, stems_dir)
                words = self.engine.transcribe(vocals, text)
                tpath.write_text(json.dumps({**key, "path": rel, "lyrics": lyrics_src, "words": words}))
            else:
                vocals = instrumentals = None

            edits = self.words.detect(words)
            if not edits:
                self._finish_linked(path, rel, key, report, via="transcript")
                return

            edit_dicts = [e.as_dict() for e in edits]
            out_rel = Path(rel).with_suffix(_out_suffix(path)).as_posix()
            out = self.s.clean / out_rel
            if (same_source and prev.get("status") == "edited" and prev.get("edits") == edit_dicts
                    and out.exists()):
                # Word list changed but this track's edits didn't.
                self.state["tracks"][rel] = {**prev, "wordlist": self.words.digest}
                report.skipped += 1
                return

            if self.s.dry_run:
                report.would_edit.append(rel)
                self._review(path, rel, edits, lyrics_src, dry=True)
                return

            if vocals is None:  # transcript was cached; stems are needed again for the edit
                stems_dir = Path(tempfile.mkdtemp(prefix="cleaner_", dir=self.s.data))
                vocals, instrumentals = self.engine.separate(path, stems_dir)

            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.parent / f".{out.name}.partial{out.suffix}"
            self.engine.render(vocals, instrumentals, edits, tmp, NATIVE_OUT.get(out.suffix, "flac"))
            tags_mod.copy_tags(path, tmp)
            tags_mod.mask_lyrics(tmp, self.words)
            self._remove_output(prev, rel, keep=out_rel)
            tmp.replace(out)
            self.state["tracks"][rel] = {**key, "status": "edited", "out": out_rel,
                                         "wordlist": self.words.digest, "edits": edit_dicts,
                                         "lyrics": lyrics_src}
            self._review(path, rel, edits, lyrics_src)
            report.edited += 1
            log.info("edited %s (%d words)", rel, len(edits))
        finally:
            if stems_dir is not None:
                shutil.rmtree(stems_dir, ignore_errors=True)

    def _finish_linked(self, path: Path, rel: str, key: dict, report: Report, via: str) -> None:
        if self.s.dry_run:
            report.linked += 1
            return
        prev = self.state["tracks"].get(rel, {})
        self._remove_output(prev, rel, keep=None)
        self._link(path, self.s.clean / rel)
        self.state["tracks"][rel] = {**key, "status": "linked", "out": rel,
                                     "wordlist": self.words.digest, "via": via}
        report.linked += 1

    # ---- files ------------------------------------------------------------------
    def _link(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.parent / f".{dst.name}.link"
        tmp.unlink(missing_ok=True)
        mode = self.s.link_mode
        if mode == "hardlink":
            try:
                os.link(src, tmp)
            except OSError as exc:  # different filesystem / mount: fall back to a copy
                log.warning("hardlink failed (%s); copying %s", exc, src.name)
                shutil.copy2(src, tmp)
        elif mode == "symlink":
            tmp.symlink_to(src)
        else:
            shutil.copy2(src, tmp)
        tmp.replace(dst)

    def _other_file(self, path: Path, rel: str) -> None:
        dst = self.s.clean / rel
        key = self._key(path)
        prev = self.state["files"].get(rel, {})
        if prev.get("size") == key["size"] and prev.get("mtime_ns") == key["mtime_ns"] \
                and prev.get("wordlist") == self.words.digest and dst.exists():
            return
        if path.suffix.lower() in LYRIC_SIDECARS:
            text = path.read_text(encoding="utf-8", errors="replace")
            masked = self.words.mask(text)
            if masked != text:
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.parent / f".{dst.name}.partial"
                tmp.write_text(masked, encoding="utf-8")
                tmp.replace(dst)
                self.state["files"][rel] = {**key, "wordlist": self.words.digest, "masked": True}
                return
        self._link(path, dst)
        self.state["files"][rel] = {**key, "wordlist": self.words.digest}

    def _remove_output(self, prev: dict, rel: str, keep: str | None) -> None:
        old = prev.get("out")
        if old and old != keep:
            (self.s.clean / old).unlink(missing_ok=True)

    def _prune(self, tracks: set, files: set) -> int:
        n = 0
        for rel in list(self.state["tracks"]):
            if rel not in tracks:
                self._remove_output(self.state["tracks"].pop(rel), rel, keep=None)
                self._transcript_path(rel).unlink(missing_ok=True)
                n += 1
        for rel in list(self.state["files"]):
            if rel not in files:
                self.state["files"].pop(rel)
                (self.s.clean / rel).unlink(missing_ok=True)
                n += 1
        return n

    def _review(self, path: Path, rel: str, edits: list[Edit], lyrics_src: str | None, dry: bool = False) -> None:
        log_path = self.s.data / ("review-dry-run.csv" if dry else "review.csv")
        new = not log_path.exists()
        artist, title = tags_mod.basic_info(path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with log_path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
            if new:
                w.writeheader()
            for e in edits:
                w.writerow({"time": now, "path": rel, "artist": artist, "title": title,
                            "start": f"{e.start:.2f}", "end": f"{e.end:.2f}", "word": e.word,
                            "heard": e.heard, "confidence": f"{e.confidence:.2f}",
                            "lyrics": lyrics_src or ""})


def run_forever(cleaner_factory, interval: int) -> None:
    while True:
        started = time.monotonic()
        report = cleaner_factory().run()
        log.info("run finished: %s", {k: v for k, v in report.as_dict().items() if k != "errors"})
        if interval <= 0:
            return
        time.sleep(max(1, interval - int(time.monotonic() - started)))
