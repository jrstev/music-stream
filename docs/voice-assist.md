# Voice: ask for any song with Home Assistant Assist

Google's assistant can't search a self-hosted library (see [landscape.md](landscape.md)). Home Assistant's own voice assistant, **Assist**, can. This setup lets you say:

> "Okay Nabu, play Teardrop by Massive Attack in the living room"

Assist then searches your library through Music Assistant and plays the best match on your Nest speaker. The search-and-play logic lives in `script.music_play_from_library`, which the AI setup in [ai-assist.md](ai-assist.md) also uses. It answers out loud ("Playing Teardrop by Massive Attack in the living room"), or tells you it couldn't find the song.

Speech recognition, intent matching and the spoken replies all run locally, with no cloud.

```
 mic (Voice PE / phone app)                                      Nest speaker
        │ audio                                                       ▲ Cast
        ▼                                                             │
 Home Assistant ── whisper (speech→text) ── custom sentence ── PlayLocalMusic ── Music Assistant
        │                                     (music.yaml)     (music_voice.yaml)  search + play
        └── piper (text→speech) → spoken reply on the mic device
```

## What you can say

| Say | Plays |
|---|---|
| "play **teardrop** by **massive attack**" | a track (artist checked against the results) |
| "play the song **paranoid android**" | a track |
| "play the song called **stand by me**" | a track; the title is never split on "by" |
| "play the album **kid a** [by **radiohead**]" | an album |
| "play music by **boards of canada**" / "play the band **radiohead**" | an artist (shuffle/all tracks per Music Assistant) |
| "play my **chill** playlist" / "play playlist **sunday morning**" | a playlist |
| "play something like **bonobo**" | an artist in radio mode (endless similar tracks) |

Add "**in the kitchen**" or "**on the office**" to any of these to choose the speaker. Without an area, the default player is used.

**Your library first, then Spotify.** If a request isn't in your library, it plays automatically from a streaming service connected in Music Assistant (see [Spotify fallback](#spotify-fallback-and-blocklist)), and the reply says so: "Playing Nightcall by Kavinsky from Spotify." Add "**from my library**" to stay in your library, or "**on Spotify**" to skip it.

**Blocking by voice:**
- "**block this song**" / "never play this song again": blocks what's playing and skips it.
- "**block Wonderwall by Oasis**" / "block the song Baby Shark" / "add Mr Brightside to my blocklist": blocks a song by name.
- "**block the artist Nickelback**" / "block Nickelback": blocks everything by an artist.
- "**unblock Wonderwall**" / "remove Nickelback from my blocked list": unblocks.

Titles that contain "by" (e.g. "Stand by Me") usually work even without "called". The intent searches both readings ("stand" by "me", and the full title "stand by me") and only accepts a result whose artist actually matches.

## Setup

**Using a Home Assistant Green?** Follow [setup-green.md](setup-green.md) instead: it covers the same steps with whisper/piper on a separate server. The steps below are for the all-in-one Docker layout (`deploy/docker-compose.yml`).

Starting from the stack in `deploy/` (see the main README):

1. **Start the voice services**
   ```sh
   cd deploy && docker compose up -d whisper piper
   # only if your satellite has no on-device wake word:
   docker compose --profile wakeword up -d openwakeword
   ```
   The first start downloads the models (a few hundred MB for `small-int8`).

2. **Load this repo's HA config.** The compose file already mounts `homeassistant/custom_sentences`, `homeassistant/packages` and `homeassistant/custom_templates` into `/config`. Add this to `deploy/data/homeassistant/configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
   Then add your per-home settings to `deploy/data/homeassistant/secrets.yaml`:
   ```yaml
   music_default_player: media_player.kitchen_speaker   # speaker used when you don't name a room
   music_allow_streaming: true                          # false = never fall back to Spotify
   music_speakers:                                      # speakers the blocklist automation watches
     - media_player.kitchen_speaker
     - media_player.living_room_speaker
   ```
   Find the entity ids under Settings → Entities, filtered by "Music Assistant". Create the blocklist (see below), then restart Home Assistant.

3. **Connect the speech engines.** Go to Settings → Devices & services → Add integration → **Wyoming Protocol**:
   - host `127.0.0.1`, port `10300` (whisper). On the Green layout, use the server's IP.
   - again with port `10200` (piper)
   - port `10400` too, if you started openwakeword

4. **Create the voice assistant.** Go to Settings → Voice assistants → Add assistant:
   - Conversation agent: **Home Assistant**
   - Speech-to-text: **faster-whisper**
   - Text-to-speech: **piper**
   
   Make it the preferred assistant.

5. **Put each Nest speaker in an area.** Check Settings → Areas, so that the Music Assistant `media_player` entity for each speaker is in the right room. The area name is what you say ("in the living room").

6. **Add a microphone.** Pick one:
   - **Home Assistant Voice Preview Edition.** The simplest option: it has an on-device wake word, adopts automatically, and you assign it to the same area as the nearby Nest speaker. Its replies come from its own small speaker; the music plays on the Nest.
   - **Home Assistant Companion app.** On Android you can make it the default digital assistant (long-press power or the home button), and Wear OS works too. On iOS, use the Assist shortcut or widget.
   - **DIY ESPHome satellite** (ESP32-S3 boards). Use openwakeword if it has no on-device wake word.

7. **Test without a microphone.** Open Assist in the HA web UI (the speech-bubble icon) and type `play teardrop by massive attack`. Settings → Voice assistants → ⋮ → *Debug* shows the matched sentence, the slots and each step.

## Spotify fallback and blocklist

### Streaming fallback
1. In Music Assistant → Settings → Providers, add **Spotify**. A Premium account is required. YouTube Music, Tidal, Qobuz, Deezer and others work the same way.
2. That's it. When a search finds nothing in your library, `script.music_play_from_library` searches your connected services and plays the best match, with the same artist check.
   - Your library always wins when it has the song.
   - "from my library" disables the fallback for one request; `allow_streaming: false` disables it entirely.

### Blocklist
Blocked songs are never played: not from your library, not from Spotify, and not when they come up inside an album, playlist or radio mode.

1. **Create the list:** Settings → Devices & services → Add integration → **Local To-do**, named **Blocked songs**. This creates `todo.blocked_songs`.
2. **Add entries** any of these ways:
   - **By voice or AI:** "block this song" while it plays, or by name: "block Wonderwall by Oasis", "block the artist Nickelback". The name is looked up in your library and on Spotify first, so the list gets the real title and artist ("block wonderwall" stores *Wonderwall* by *Oasis*). If nothing is found, it's stored as you said it. If the song is playing somewhere right now, it's skipped immediately.
   - **In the app:** HA app → To-do lists → Blocked songs → add an item:

   | Item | Description | Blocks |
   |---|---|---|
   | `Teardrop` | `Massive Attack` | that song by that artist (any version: "Teardrop - Remastered", "Teardrop (Live)", …) |
   | `Wonderwall` | *(empty)* | that title by any artist |
   | `*` | `Nickelback` | everything by that artist, including "play music by Nickelback" |

   Matching ignores case, punctuation, and "(…)" / "[…]" / " - …" suffixes.
3. **Unblock** by saying "unblock Wonderwall" / "unblock Nickelback", or tick the item off / delete it in the app. Saying "unblock Wonderwall" with no artist removes every *Wonderwall* entry.

How it's enforced:
- **Requests:** the play script and the search tool skip blocked results. A request that matches a blocked song gets "… is on your blocked list" and is never retried on Spotify.
- **During playback:** `automation.music_skip_blocked_songs` watches the speakers you listed. When a blocked song starts, it skips to the next track and writes a logbook entry. Expect a second or two of the song before it's skipped.

## Optional: let an AI interpret requests

For requests like "play the song from Drive" or "something mellow for cooking", put an AI model (Anthropic Claude in the cloud, or Ollama locally) in front of the same scripts. See [ai-assist.md](ai-assist.md).

## Tuning

- **Recognition of odd names.** Whisper sometimes mishears unusual artist names. Options:
  - a larger model (`WHISPER_MODEL=medium-int8`, or a GPU build)
  - saying the artist's more common spelling
  - adding the AI agent above, which handles near-misses well
- **Raspberry Pi.** Use `WHISPER_MODEL=base-int8`, or run whisper on a faster machine on your network (point the Wyoming integration at it).
- **Other languages.** Set `VOICE_LANGUAGE` and `PIPER_VOICE`, and translate `custom_sentences/en/music.yaml` into `custom_sentences/<lang>/`.

## Status

The sentence matching and the result-selection logic are unit-tested:
- `tests/test_voice_sentences.py` runs the phrases through hassil, the matcher HA itself uses.
- `tests/test_music_voice_templates.py` renders the scripts' templates and the shared `custom_templates/music_voice.jinja` macros against fake search results and to-do lists. That covers library-first ordering, the Spotify fallback, and blocklist matching.

The Home Assistant side (the `music_assistant.search` response shape, `config_entry_id()`, area lookup) has not been run against a live install yet. If something misbehaves, the Assist debug view shows which step failed.
