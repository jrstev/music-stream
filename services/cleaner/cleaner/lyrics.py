"""Find reference lyrics for a track: sidecar .lrc/.txt, embedded tags, or Genius."""

from __future__ import annotations

import re
from pathlib import Path

_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]|<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_LRC_META = re.compile(r"^\[[a-z#]+:[^\]]*\]$", re.I)

SIDECAR_EXTS = (".lrc", ".txt")


def strip_lrc(text: str) -> str:
    """LRC -> plain text: drop [mm:ss.xx] / <mm:ss.xx> stamps and [ar:...]-style header lines."""
    lines = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or _LRC_META.match(line):
            continue
        line = _TIMESTAMP.sub("", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def sidecar_path(audio: Path) -> Path | None:
    for ext in SIDECAR_EXTS:
        p = audio.with_suffix(ext)
        if p.exists():
            return p
    return None


def embedded(audio: Path) -> str | None:
    """Lyrics stored in the file's tags (ID3 USLT/SYLT, Vorbis LYRICS, MP4 ©lyr)."""
    import mutagen

    try:
        f = mutagen.File(str(audio))
    except Exception:
        return None
    if f is None or f.tags is None:
        return None
    tags = f.tags

    # ID3 (MP3, also WAV/AIFF with ID3)
    if hasattr(tags, "getall"):
        for frame in tags.getall("USLT"):
            if str(frame.text).strip():
                return str(frame.text)
        for frame in tags.getall("SYLT"):
            text = " ".join(t for t, _ in frame.text).strip()
            if text:
                return text
        return None

    # Vorbis comments (FLAC, Ogg) and MP4 atoms
    for key in ("LYRICS", "lyrics", "UNSYNCEDLYRICS", "unsyncedlyrics", "\xa9lyr"):
        try:
            value = tags.get(key)
        except Exception:
            value = None
        if value:
            text = "\n".join(str(v) for v in (value if isinstance(value, list) else [value]))
            if text.strip():
                return text
    return None


def find(audio: Path, genius_token: str | None = None) -> tuple[str | None, str | None]:
    """Return (plain lyrics, source) with source in {"sidecar", "embedded", "genius"}, or (None, None)."""
    side = sidecar_path(audio)
    if side:
        text = strip_lrc(side.read_text(encoding="utf-8", errors="replace"))
        if text.strip():
            return text, "sidecar"
    text = embedded(audio)
    if text and text.strip():
        return strip_lrc(text), "embedded"
    if genius_token:
        try:
            from music_profanity_filter.lyrics import LyricsFetcher

            text = LyricsFetcher(access_token=genius_token).fetch_from_file(audio)
        except Exception:
            text = None
        if text and text.strip():
            return text, "genius"
    return None, None
