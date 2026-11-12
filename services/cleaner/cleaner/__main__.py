"""python -m cleaner [--once | --interval SECONDS] [--dry-run]

Settings come from environment variables (see deploy/cleaner/README in docs/clean-library.md):
  SOURCE_DIR, CLEAN_DIR, DATA_DIR, WORDLIST, LINK_MODE, TRUST_LYRICS, GENIUS_ACCESS_TOKEN,
  PRUNE, WHISPER_MODEL, DEMUCS_MODEL, PAD_MS, MP3_BITRATE, INTERVAL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .processor import Cleaner, Settings, run_forever


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def settings_from_env(dry_run: bool = False) -> Settings:
    wl = os.environ.get("WORDLIST", "/config/words.txt")
    return Settings(
        source=Path(os.environ.get("SOURCE_DIR", "/media/music")),
        clean=Path(os.environ.get("CLEAN_DIR", "/media/music-clean")),
        data=Path(os.environ.get("DATA_DIR", "/data")),
        wordlist_path=Path(wl) if wl else None,
        link_mode=os.environ.get("LINK_MODE", "hardlink"),
        trust_lyrics=_bool("TRUST_LYRICS", True),
        genius_token=os.environ.get("GENIUS_ACCESS_TOKEN") or None,
        prune=_bool("PRUNE", True),
        dry_run=dry_run or _bool("DRY_RUN", False),
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cleaner", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true", help="run once and exit (default unless INTERVAL is set)")
    p.add_argument("--interval", type=int, default=int(os.environ.get("INTERVAL", "0")),
                   help="re-scan every N seconds (0 = once)")
    p.add_argument("--dry-run", action="store_true",
                   help="detect and log to review-dry-run.csv; write nothing to CLEAN_DIR")
    args = p.parse_args(argv)

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")

    from .engine import MpfEngine

    engine = MpfEngine(
        demucs_model=os.environ.get("DEMUCS_MODEL", "htdemucs"),
        whisper_model=os.environ.get("WHISPER_MODEL", "small"),
        pad_ms=int(os.environ.get("PAD_MS", "80")),
        bitrate=os.environ.get("MP3_BITRATE", "320k"),
    )
    settings = settings_from_env(args.dry_run)
    # Re-create the Cleaner each pass so word-list edits are picked up without a restart.
    run_forever(lambda: Cleaner(settings, engine), 0 if args.once else args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
