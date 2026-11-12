"""Copy tags from the original onto the cleaned file, and mask lyric tags.

music-profanity-filter only copies ID3 tags (MP3) and appends " (clean)" to the
title; here every supported format gets its original tags back unchanged
(so Navidrome shows normal titles), and lyric tags get list words masked.
"""

from __future__ import annotations

import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, SYLT, USLT, ID3NoHeaderError
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from .wordlist import WordList

LYRIC_KEYS = ("LYRICS", "UNSYNCEDLYRICS")


def _vorbis_like(f) -> bool:
    return isinstance(f, (FLAC, OggVorbis, OggOpus))


def copy_tags(src: Path, dst: Path) -> None:
    s = mutagen.File(str(src))
    d = mutagen.File(str(dst))
    if s is None or d is None or s.tags is None:
        return

    # MP3 -> MP3: copy every ID3 frame verbatim (replaces anything the filter wrote).
    if dst.suffix.lower() == ".mp3":
        try:
            src_id3 = ID3(str(src))
        except ID3NoHeaderError:
            return
        try:
            dst_id3 = ID3(str(dst))
            dst_id3.clear()
        except ID3NoHeaderError:
            dst_id3 = ID3()
        for frame in src_id3.values():
            dst_id3.add(frame)
        dst_id3.save(str(dst))
        return

    # Vorbis-comment formats with the same container: copy comments (+ FLAC pictures).
    if _vorbis_like(d) and type(s) is type(d):
        d.delete()
        if d.tags is None:
            d.add_tags()
        for key, values in s.tags.items():
            d.tags[key] = list(values)
        if isinstance(s, FLAC):
            d.clear_pictures()
            for pic in s.pictures:
                d.add_picture(pic)
        d.save()
        return

    # Anything else -> FLAC (we write M4A/Opus/... sources as FLAC): map common fields.
    if isinstance(d, FLAC):
        easy = mutagen.File(str(src), easy=True)
        d.delete()
        if d.tags is None:
            d.add_tags()
        if easy is not None and easy.tags is not None:
            for key, values in easy.tags.items():
                d.tags[key] = [str(v) for v in values]
        d.clear_pictures()
        for pic in _pictures(s):
            d.add_picture(pic)
        lyr = _mp4_lyrics(s)
        if lyr:
            d.tags["LYRICS"] = [lyr]
        d.save()


def _pictures(f) -> list[Picture]:
    pics = []
    tags = f.tags
    if tags is None:
        return pics
    if "covr" in tags:  # MP4
        for cover in tags["covr"]:
            p = Picture()
            p.type = 3
            p.mime = "image/png" if getattr(cover, "imageformat", None) == 14 else "image/jpeg"
            p.data = bytes(cover)
            pics.append(p)
    for b64 in tags.get("metadata_block_picture", []) if hasattr(tags, "get") else []:
        try:
            pics.append(Picture(base64.b64decode(b64)))
        except Exception:
            pass
    return pics


def _mp4_lyrics(f) -> str | None:
    try:
        value = f.tags.get("\xa9lyr")
    except Exception:
        return None
    return "\n".join(value) if value else None


def mask_lyrics(path: Path, words: WordList) -> bool:
    """Mask list words in the file's lyric tags. Returns True if anything changed."""
    f = mutagen.File(str(path))
    if f is None or f.tags is None:
        return False
    changed = False
    tags = f.tags

    if hasattr(tags, "getall"):  # ID3
        for frame in tags.getall("USLT"):
            masked = words.mask(str(frame.text))
            if masked != frame.text:
                frame.text, changed = masked, True
        for frame in tags.getall("SYLT"):
            new = [(words.mask(t), ts) for t, ts in frame.text]
            if new != frame.text:
                frame.text, changed = new, True
    else:
        for key in list(LYRIC_KEYS) + [k.lower() for k in LYRIC_KEYS] + ["\xa9lyr"]:
            try:
                values = tags.get(key)
            except Exception:
                values = None
            if not values:
                continue
            new = [words.mask(str(v)) for v in values]
            if new != [str(v) for v in values]:
                tags[key] = new
                changed = True
    if changed:
        f.save()
    return changed


def basic_info(path: Path) -> tuple[str, str]:
    """(artist, title) for logs; falls back to the filename."""
    try:
        f = mutagen.File(str(path), easy=True)
        tags = f.tags if f is not None else None
        artist = (tags.get("artist") or [""])[0] if tags else ""
        title = (tags.get("title") or [""])[0] if tags else ""
    except Exception:
        artist, title = "", ""
    return artist, title or path.stem
