"""Word list: loading, matching and masking.

Matching follows music-profanity-filter's detector so that what we mute in the
audio and what we mask in lyric tags agree:
  * a token matches if, lowercased with punctuation removed, it equals a list word, or
  * a list word of 4+ characters appears inside it (catches compounds).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_TOKEN = re.compile(r"\w+")


def _normalize(token: str) -> str:
    return re.sub(r"[^\w]", "", token.lower())


@dataclass(frozen=True)
class Edit:
    """One word to mute: the list word it matched, what was heard, and when."""

    word: str
    heard: str
    start: float
    end: float
    confidence: float = 1.0

    def as_dict(self) -> dict:
        return {"word": self.word, "heard": self.heard, "start": round(self.start, 3),
                "end": round(self.end, 3), "confidence": round(self.confidence, 3)}


class WordList:
    def __init__(self, words):
        self.words = frozenset(w.strip().lower() for w in words if w and w.strip())
        self._contained = sorted((w for w in self.words if len(w) >= 4), key=len, reverse=True)

    # ---- loading ------------------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "WordList":
        words = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
        return cls(words)

    @classmethod
    def from_file(cls, path: Path) -> "WordList":
        return cls.parse(Path(path).read_text(encoding="utf-8"))

    @classmethod
    def builtin(cls) -> "WordList":
        """music-profanity-filter's bundled list (requires the package)."""
        from importlib.resources import files

        return cls.parse((files("music_profanity_filter") / "data" / "profanity.txt").read_text("utf-8"))

    @classmethod
    def load(cls, path: Path | None) -> "WordList":
        if path and Path(path).exists():
            wl = cls.from_file(path)
            if wl.words:
                return wl
        return cls.builtin()

    @property
    def digest(self) -> str:
        return hashlib.sha256("\n".join(sorted(self.words)).encode()).hexdigest()[:16]

    # ---- matching -------------------------------------------------------------
    def match(self, token: str) -> str | None:
        norm = _normalize(token)
        if not norm:
            return None
        if norm in self.words:
            return norm
        for w in self._contained:
            if w in norm:
                return w
        return None

    def check_text(self, text: str) -> list[str]:
        """List words that occur in free text (e.g. lyrics), in order of first appearance."""
        found: list[str] = []
        for token in _TOKEN.findall(text or ""):
            hit = self.match(token)
            if hit and hit not in found:
                found.append(hit)
        return found

    def detect(self, words: list[dict]) -> list[Edit]:
        """Words from a transcription ({word, start, end, confidence}) that need muting."""
        edits = []
        for w in words:
            hit = self.match(w.get("word", ""))
            if hit:
                edits.append(Edit(hit, w["word"].strip(), float(w["start"]), float(w["end"]),
                                  float(w.get("confidence", 1.0))))
        return edits

    def mask(self, text: str) -> str:
        """Replace matching words in text with first letter + asterisks."""
        def repl(m: re.Match) -> str:
            tok = m.group(0)
            return tok[0] + "*" * (len(tok) - 1) if self.match(tok) else tok

        return _TOKEN.sub(repl, text or "")
