"""The heavy audio work, behind a small interface so it can be swapped or faked in tests.

MpfEngine uses music-profanity-filter's components (Demucs stem separation,
Whisper word timestamps, mute + remix). Imports are lazy: the models are only
loaded when a track actually needs audio processing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .wordlist import Edit


class Engine(Protocol):
    def separate(self, audio: Path, workdir: Path) -> tuple[Path, Path]:
        """Split into (vocals, instrumentals) files inside workdir."""

    def transcribe(self, vocals: Path, lyrics: str | None) -> list[dict]:
        """Word timestamps: [{"word", "start", "end", "confidence"}, ...]."""

    def render(self, vocals: Path, instrumentals: Path, edits: list[Edit], out: Path, fmt: str) -> None:
        """Mute `edits` in the vocals, remix with instrumentals, write `out` in format `fmt`."""


class MpfEngine:
    def __init__(self, demucs_model: str = "htdemucs", whisper_model: str = "small",
                 pad_ms: int = 80, bitrate: str = "320k"):
        self.demucs_model = demucs_model
        self.whisper_model = whisper_model
        self.pad = pad_ms / 1000.0
        self.bitrate = bitrate
        self._separator = self._transcriber = self._editor = None

    def _components(self):
        if self._separator is None:
            from music_profanity_filter.editor import AudioEditor
            from music_profanity_filter.separator import StemSeparator
            from music_profanity_filter.transcriber import Transcriber

            self._separator = StemSeparator(model=self.demucs_model)
            self._transcriber = Transcriber(model_size=self.whisper_model)
            self._editor = AudioEditor()
        return self._separator, self._transcriber, self._editor

    def separate(self, audio: Path, workdir: Path) -> tuple[Path, Path]:
        separator, _, _ = self._components()
        stems = separator.separate(audio, output_dir=workdir)
        return Path(stems["vocals"]), Path(stems["instrumentals"])

    def transcribe(self, vocals: Path, lyrics: str | None) -> list[dict]:
        _, transcriber, _ = self._components()
        words = (transcriber.transcribe_with_context(vocals, lyrics) if lyrics
                 else transcriber.transcribe(vocals))
        return [{"word": w.word, "start": float(w.start), "end": float(w.end),
                 "confidence": float(getattr(w, "confidence", 1.0))} for w in words]

    def render(self, vocals: Path, instrumentals: Path, edits: list[Edit], out: Path, fmt: str) -> None:
        from music_profanity_filter.detector import ProfanityMatch

        _, _, editor = self._components()
        # Whisper word boundaries are approximate: widen each edit a little.
        matches = [ProfanityMatch(word=e.word, original_word=e.heard, start=max(0.0, e.start - self.pad),
                                  end=e.end + self.pad, confidence=e.confidence) for e in edits]
        edited = out.parent / f".{out.stem}.edited-vocals.wav"
        try:
            editor.mute_profanities(vocals, matches, edited)
            editor.combine_stems(edited, instrumentals, out, output_format=fmt, bitrate=self.bitrate)
        finally:
            edited.unlink(missing_ok=True)
