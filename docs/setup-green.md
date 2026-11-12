# Setup: Home Assistant Green + a home server

The recommended layout. The Green does what it's good at; a PC or NAS does the heavy lifting.

```
          Home Assistant Green                         PC / NAS (Docker)
 ┌───────────────────────────────────────┐   LAN   ┌─────────────────────────────┐
 │ Home Assistant                        │ ──────► │ whisper :10300 (speech→text)│
 │   voice config from this repo         │ ──────► │ piper   :10200 (replies)    │
 │   (scripts, sentences, blocklist)     │ ──────► │ ollama  :11434 (optional AI)│
 │ Music Assistant add-on ───────────────┼───────► │ Navidrome :4533 (library)   │
 │      │ Cast                           │         │ cleaner (optional)          │
 └──────┼────────────────────────────────┘         └─────────────────────────────┘
        ▼
   Nest speakers          microphone: Home Assistant Voice PE / phone app
```

**Why split it?**
- **Music Assistant** is light and must sit on the speakers' network, so it goes on the Green.
- **Speech-to-text for arbitrary song names** needs Whisper, which is slow on the Green's processor, so it goes on the server.
- **The cleaner** needs a PC, ideally with a GPU.
- **Your music** already lives on the server or NAS anyway.

Give both machines a fixed IP: a DHCP reservation on your router. Below, the server is `192.168.1.20`; use your own address.

## 1. Server (PC/NAS)

```sh
git clone <this repo> music-stream && cd music-stream/deploy/server
cp .env.example .env && $EDITOR .env      # MUSIC_DIR at minimum
docker compose up -d                      # Navidrome, whisper, piper
```

- Open `http://192.168.1.20:4533`, create the Navidrome admin user, and let it scan.
- Optional extras:
  - `docker compose --profile cleaner up -d --build` adds the clean library ([clean-library.md](clean-library.md)).
  - `docker compose --profile ai-local up -d` adds a local AI model ([ai-assist.md](ai-assist.md)).
- Keep these ports on your LAN. Don't forward them on your router.

## 2. Home Assistant Green: Music Assistant

1. **Install Music Assistant:** Settings → Add-ons → Add-on store → **Music Assistant** → Install → Start. Turn on "Start on boot".
2. **Add your music:** in Music Assistant (sidebar) → Settings → Providers → Add **Subsonic**. Server `http://192.168.1.20`, port `4533`, with your Navidrome user.
   - No Navidrome? Music Assistant can also read a network share directly (*Filesystem (remote share)* provider).
3. **Add the speakers:** Providers → Add **Google Cast**. Your Nest speakers appear as players. Play something from the Music Assistant UI to check.
4. **Optional:** add **Spotify** (Premium) for the streaming fallback.
5. **Connect it to Home Assistant:** Settings → Devices & services → the discovered **Music Assistant** integration → Configure.
6. **Name your rooms:** Settings → Areas. Put each Nest speaker's Music Assistant player in the right area, e.g. "Kitchen". The area names are what you say ("in the kitchen").

## 3. Home Assistant Green: this repo's voice config

1. **Turn on file access** with one add-on:
   - **Terminal & SSH:** add your public key in its configuration and start it. The sync script then works over SSH.
   - **Samba share:** set a password, start it, and mount the `config` share on your computer (Finder → Go → Connect to server → `smb://homeassistant.local`, or `\\homeassistant.local\config` on Windows).
2. **Create the blocklist:** Settings → Devices & services → Add integration → **Local To-do** → name it **Blocked songs**.
3. **Copy the config** from your computer, in the repo folder:
   ```sh
   scripts/sync-ha-config.sh root@homeassistant.local --add-secrets   # SSH
   # or: scripts/sync-ha-config.sh /Volumes/config --add-secrets     # mounted Samba share
   ```
   This copies `custom_sentences/`, `packages/` and `custom_templates/` into `/config` and nothing else. It then tells you if `configuration.yaml` needs this:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
   You can add that with the File editor add-on.
4. **Edit your settings in `secrets.yaml`.** `--add-secrets` adds placeholders. Set them to your speakers' Music Assistant entity ids, found in Settings → Entities, filtered by "Music Assistant":
   ```yaml
   music_default_player: media_player.kitchen_speaker   # used when you don't name a room
   music_allow_streaming: true                          # false = never fall back to Spotify
   music_speakers:                                      # speakers the blocklist automation watches
     - media_player.kitchen_speaker
     - media_player.living_room_speaker
   ```
   These live only on the Green, so re-running the sync script never overwrites them.
5. **Restart Home Assistant:** Settings → System → Restart, or use `--restart` with the SSH form.

Re-run step 3 (without `--add-secrets`) whenever you update the repo.

## 4. Home Assistant Green: voice

1. **Speech engines on the server:** Settings → Devices & services → Add integration → **Wyoming Protocol**:
   - host `192.168.1.20`, port `10300` (whisper)
   - again with port `10200` (piper)
2. **Voice assistant:** Settings → Voice assistants → Add assistant:
   - Conversation agent: **Home Assistant**, or an AI agent per [ai-assist.md](ai-assist.md)
   - Speech-to-text: **faster-whisper**
   - Text-to-speech: **piper**
   
   Make it the preferred assistant.
3. **Microphone:**
   - **Home Assistant Voice Preview Edition** (adopts automatically; put it in the same area as the nearby Nest speaker), or
   - the **Home Assistant app** on your phone.
4. **Test by typing** in the Assist dialog: `play teardrop by massive attack in the kitchen`. Then by voice.

The rest of the voice docs apply unchanged: [voice-assist.md](voice-assist.md) (phrases, Spotify fallback, blocklist) and [ai-assist.md](ai-assist.md). Wherever they say "127.0.0.1", use the server's IP.

## Troubleshooting

- **Wyoming "Failed to connect":** check that the server's firewall allows 10300/10200 from the Green, and that `docker compose ps` shows whisper/piper running.
- **"I don't know of a Music Assistant speaker in the kitchen":** the player isn't assigned to that area (step 2.6).
- **Configuration errors after restart, e.g. "Secret music_speakers not defined":** finish step 3.4.
- **Speakers missing in Music Assistant:** the Green and the speakers must be on the same network/VLAN. Cast discovery doesn't cross subnets without an mDNS reflector.
