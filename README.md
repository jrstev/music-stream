# music-stream

Play your own self-hosted music library on Google Home / Nest speakers, by voice.

## The short answer

- **You can't register a self-hosted server as a Google Home music service**, and you can't replace the default one. The provider list is partner-only (Media Actions). Conversational Actions were shut down in 2023. Gemini for Home uses the same partner model. Details and sources are in [`docs/landscape.md`](docs/landscape.md).
- **You don't need to build the streaming part.** Existing open-source tools already do it well. Nest speakers are Cast receivers, and **Music Assistant** can push your library to them (including speaker groups).
- **The missing piece is voice.** Google won't send "play X" to you, so this repo covers two routes:
  - **Any song, any artist:** Home Assistant **Assist**, fully local. "Okay Nabu, play Teardrop by Massive Attack in the living room" searches your library and plays it on the Nest speaker. See [`docs/voice-assist.md`](docs/voice-assist.md).
  - **Spotify fallback and blocklist:** anything not in your library plays automatically from Spotify (or another service connected in Music Assistant). Songs and artists on your blocklist are never played. See [`docs/voice-assist.md`](docs/voice-assist.md#spotify-fallback-and-blocklist).
  - **Clean library (optional):** mute words from your own word list in your own files. It makes a clean copy of the library, using lyrics for accuracy, and Navidrome serves that copy. See [`docs/clean-library.md`](docs/clean-library.md).
  - **Natural requests with AI:** put Claude (cloud) or an Ollama model (local) in front, so "play the song from Drive" or "something mellow for cooking" works too. See [`docs/ai-assist.md`](docs/ai-assist.md).
  - **"Hey Google" for favorites:** Google Home routines with fixed phrases that trigger Home Assistant scripts, generated from your playlists (below).

## Architecture

```
 ┌──────────────┐   Subsonic API    ┌───────────────────┐    Cast (LAN)    ┌──────────────┐
 │  Navidrome   │ ◄──────────────── │  Music Assistant  │ ───────────────► │ Nest/Google  │
 │ (home or VPS)│                   │   (on the LAN)    │                  │   speakers   │
 └──────────────┘                   └─────────▲─────────┘                  └──────┬───────┘
                                              │ music_assistant.play_media        │ "Hey Google, play
                                    ┌─────────┴─────────┐   scene activate        │  my jazz playlist"
                                    │  Home Assistant   │ ◄─────── Google Home routine
                                    │ scripts (generated)│        (generated)
                                    └───────────────────┘
```

## Setup

1. **Run the stack** on a machine on the same LAN as the speakers:
   ```sh
   cd deploy && cp .env.example .env && $EDITOR .env && docker compose up -d
   ```
   Navidrome runs on `:4533`, Music Assistant on `:8095`, and Home Assistant on `:8123`. If your library lives on a VPS, run Navidrome there behind HTTPS or Tailscale, and drop it from the compose file.
2. **Music Assistant:** add the *Subsonic* (Navidrome) music provider and the *Google Cast* player provider. Check that you can play to a Nest speaker from the MA UI.
3. **Home Assistant:** add the *Music Assistant* integration. Then connect HA to Google: either Nabu Casa Cloud (easiest) or the free [manual Google Assistant integration](https://www.home-assistant.io/integrations/google_assistant/). Make sure `script` entities are exposed.
4. **Generate voice commands:**
   ```sh
   SUBSONIC_URL=http://localhost:4533 SUBSONIC_USER=me SUBSONIC_PASSWORD=secret \
   python3 tools/gen_voice_routines.py \
     --speaker kitchen=media_player.kitchen_speaker \
     --speaker "living room=media_player.living_room_speaker" \
     --default-speaker kitchen \
     --artist "Boards of Canada"
   ```
   - `out/ha_scripts.yaml`: add it to Home Assistant (`script: !include ha_scripts.yaml`), then reload scripts. Ask Google to "sync my devices". The scripts then show up as scenes.
   - `out/google_home_routines.yaml`: paste it into the Google Home **script editor** (home.google.com → Automations → Add new). Use the editor's autocomplete if a scene name needs a suffix (`--device-suffix`).
5. Say **"Hey Google, play my jazz playlist"** or **"…play my jazz playlist in the living room"**.
6. **Any-song voice control:** follow [`docs/voice-assist.md`](docs/voice-assist.md). It covers the local whisper/piper services already in the compose file, the music scripts and intent, and a microphone such as Home Assistant Voice PE or the HA phone app.
7. **AI interpretation (optional):** follow [`docs/ai-assist.md`](docs/ai-assist.md) to let Claude or a local Ollama model parse requests and call the music scripts as tools.

Re-run step 4 whenever you add playlists. You can change the phrasing with `--phrase` and `--room-phrase`. Phrases start with "play my …" so Google's built-in "play X" handling is less likely to take over.

## Limitations

- "Hey Google" phrases are fixed, one per playlist/artist and room. There's no free-form search through Google. Free-form requests go through Assist, which needs its own microphone (Voice PE, the phone app, or an ESPHome satellite); the Nest speakers stay as outputs.
- Transport controls ("Hey Google, pause") on a speaker that's casting from Music Assistant generally work. Results vary by firmware and Gemini rollout.
- Music Assistant must run on the speakers' LAN (Cast uses mDNS discovery).

## Development

```sh
pip install hassil jinja2 pyyaml mutagen   # optional: enables the Assist and cleaner tests (cleaner tests also need ffmpeg)
python3 -m unittest discover -s tests
```
