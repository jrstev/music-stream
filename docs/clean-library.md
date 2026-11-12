# Clean library: mute listed words in your own music

The `cleaner` service makes a **clean copy** of your library next to the original. In the copy, words from your word list are muted in the vocals; the music keeps playing underneath. Point Navidrome at the copy, and everything downstream plays the clean versions: Music Assistant, the voice commands, the Nest speakers.

```
/srv/music         (originals: only ever read)
/srv/music-clean   (what Navidrome serves)
   ├─ songs with no listed words   → hardlinks to the originals (no extra disk space)
   ├─ songs with listed words      → new files: vocals muted at those words, original tags kept
   └─ cover art, .lrc lyrics, …    → linked; lyrics files and lyric tags have listed words masked (f***)
```

It's built on [music-profanity-filter](https://github.com/curtisgibby/music-profanity-filter) (MIT), pinned to a known commit:
- Demucs separates the vocals from the rest of the song.
- Whisper transcribes the vocals with word timestamps.
- Those words are muted in the vocal track only, then the song is remixed.

This repo adds the library-level work around it:
- finding lyrics
- caching transcripts
- incremental runs
- copying tags for every format
- hardlinking unchanged songs
- a review log

## Lyrics make it much more accurate

Whisper alone misses words in fast or heavily produced vocals. Given the song's lyrics, the transcription is aligned against them, so a word Whisper half-hears is still caught. For each song the cleaner looks for lyrics in this order:

1. A **sidecar file** next to the song with the same name: `Song.lrc` or `Song.txt`. Timestamps and `[ar:…]` header lines are stripped.
2. **Embedded lyrics** in the file's tags: MP3 `USLT`/`SYLT`, FLAC/Ogg `LYRICS`/`UNSYNCEDLYRICS`, M4A `©lyr`.
3. **Genius**, if `GENIUS_ACCESS_TOKEN` is set. It uses the artist and title from the tags. A token is free from genius.com/api-clients.

Lyrics also make clean songs fast. When a song's lyrics contain none of your words, it's linked unchanged **without running the AI models at all** (`TRUST_LYRICS=true`, the default). Set `TRUST_LYRICS=false` if your lyric files are unreliable; every song is then analysed.

## Setup

1. **Put both folders under one parent** on the same disk. The cleaner mounts the parent so it can hardlink unchanged songs; hardlinks don't work across mounts or disks. In the `.env` next to the compose file (`deploy/server/.env` on the Green layout):
   ```sh
   MEDIA_ROOT=/srv            # contains your music folder
   MUSIC_SUBDIR=music         # /srv/music  (originals)
   CLEAN_SUBDIR=music-clean   # /srv/music-clean (created)
   ```
   The cleaner never writes inside the originals folder; it refuses to start if one folder is inside the other.
2. **Write your word list** in `deploy/cleaner/words.txt`, one word per line. Matching rules:
   - case doesn't matter
   - listed words of 4+ letters also match inside longer words
   - shorter words only match exactly
   
   If the file has no words, music-profanity-filter's built-in list is used.
3. **Try a dry run first.** It analyses and logs, but writes nothing to the clean folder:
   ```sh
   cd deploy/server      # or deploy/ for the all-in-one layout
   docker compose --profile cleaner build cleaner
   docker compose --profile cleaner run --rm cleaner --dry-run --once
   ```
   Then read `data/cleaner/review-dry-run.csv` (next to the compose file): one row per word to be muted, with timestamp, what was heard, and confidence.
4. **Run it for real** as a background service that re-scans every 6 hours (`CLEANER_INTERVAL`, in seconds):
   ```sh
   docker compose --profile cleaner up -d cleaner
   ```
5. **Point Navidrome at the clean copy:** set `NAVIDROME_MUSIC_DIR=/srv/music-clean` in `.env`, then `docker compose up -d navidrome`. Music Assistant picks it up through Navidrome on its next sync.
   - Want both? Run a second Navidrome instance (or a second library) on the originals, e.g. a "family" library and an "everything" library.

## Day to day

- **New music:** picked up on the next pass. Only new or changed files are processed.
- **Editing the word list:** the next pass re-checks every song using **cached transcripts**, so no re-transcription is needed. Only songs whose edits actually changed get re-rendered. Removing a word turns affected songs back into links to the originals.
- **Deleted originals:** removed from the clean copy (`PRUNE=true`).
- **Review:** `data/cleaner/review.csv` (next to the compose file) logs every muted word (song, start/end time, list word, what was heard, confidence, lyrics source). `last_run.json` has the counts from the latest pass, including failures with their error messages.
- **A song was muted wrongly or missed a word:** check its row in `review.csv`. The usual fix is adding a lyrics file next to the song (`Song.lrc` or `Song.txt`) and touching the song file (`touch "Song.mp3"`) so it's re-analysed on the next pass.

## Settings

| Variable (`.env`) | Default | Meaning |
|---|---|---|
| `CLEANER_WHISPER_MODEL` | `small` | `tiny`/`base`/`small`/`medium`/`large`. Bigger is more accurate and slower. |
| `CLEANER_DEMUCS_MODEL` | `htdemucs` | Also `htdemucs_ft` (better, slower) or `mdx_extra`. |
| `CLEANER_TRUST_LYRICS` | `true` | Skip analysis when the lyrics contain no listed words. |
| `GENIUS_ACCESS_TOKEN` | *(empty)* | Fetch lyrics for songs that have none. |
| `CLEANER_INTERVAL` | `21600` | Seconds between passes (`0` = run once and exit). |
| `CLEANER_TORCH_INDEX` | CPU wheels | `https://download.pytorch.org/whl/cu124` for an NVIDIA GPU (and uncomment the GPU block in compose). |

Service-level variables (set under the service in `docker-compose.yml`):
- `PAD_MS` (default 80): milliseconds of extra silence either side of each muted word.
- `MP3_BITRATE` (default `320k`)
- `LINK_MODE`: `hardlink`, `copy` or `symlink`
- `PRUNE`
- `LOG_LEVEL`

## What to expect

- **Speed:** a 3-4 minute song takes roughly a few minutes on a CPU and well under a minute on a mid-range NVIDIA GPU. Songs settled by their lyrics take a fraction of a second. The first pass over a big library is the slow one: consider a GPU, or let it run overnight.
- **Accuracy:** good with lyrics, decent without. Expect occasional misses on fast or heavily layered vocals, and occasional false hits. Review the CSV after the first pass.
- **Audio:**
  - **Edited songs:** separating and remixing isn't perfectly transparent. Edited songs can have faint artifacts, and MP3s are re-encoded at 320 kbps.
  - **Unchanged songs** are the original files, untouched.
  - **Formats:** MP3, FLAC, Ogg and WAV are written back in their own format. M4A/AAC, Opus and others are written as FLAC (lossless), with tags and cover art carried over.
- **Disk:** only edited songs take extra space.
- **Spotify/streaming isn't covered.** Streams can't be modified. Use Spotify's own "Allow explicit content" setting on the account Music Assistant uses.

## Status

- `tests/test_cleaner.py` runs the whole library pipeline against real (generated, silent) MP3/FLAC/M4A files, with a fake engine in place of Demucs/Whisper. It covers:
  - lyrics discovery and lyrics-only skipping
  - transcript caching and word-list changes
  - hardlinks, tag copying, title restoration, lyric masking
  - format conversion, pruning, dry runs and failure retry
- **Not yet run:**
  - the Docker image build
  - the real Demucs/Whisper/remix calls (`cleaner/engine.py`). These call music-profanity-filter's components exactly as its pinned source defines them, but haven't been executed here.
  
  Run a dry run on a few songs first.
