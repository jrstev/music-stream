# Landscape: self-hosted music on Google Home / Nest speakers

Research as of November 2026.

## 1. Can a self-hosted server be *the* music service in Google Home?

**No. Nothing that exists today makes this possible, and you cannot build it yourself.**

| Route | Status | Why it doesn't work |
|---|---|---|
| Default music service list (Spotify, YouTube Music, Pandora, Apple Music, Deezer, …) | Closed list | Providers are onboarded by Google through business partnerships. |
| **Media Actions** (feed-based "play X on Y") | Partner-gated | Google says it is "working with a limited number of providers". You host a catalog feed, pass a quality checklist, and then Google has to accept you. That isn't realistic for a personal library. |
| Conversational Actions ("Talk to my music server") | **Shut down June 2023** | The Actions on Google conversational platform was retired. |
| Android MediaSession + Assistant | Phone/Android only | It lets Assistant control an app *on an Android phone*. It doesn't apply to Nest speakers, and URI-based "play X" still requires providing URIs to Google. |
| Gemini for Home | Same model | Gemini replaced Assistant on speakers, but music still comes from first-party/partner integrations (YouTube Music, Spotify, …). Google's new Home APIs are about devices and automations, not media catalogs. |
| Disable default music and substitute your own | Not possible | You can only pick from the partner list. "Play \<anything\>" always goes to Google's resolver. |

So you can't get a free-form "Hey Google, play Boards of Canada" to resolve against your own library.

## 2. What *does* work

The speakers are **Google Cast receivers**. Anything on your LAN that speaks the Cast protocol can push an HTTP audio stream to them. That part is mature and works well.

### Library servers (where the music lives)

| Server | Notes |
|---|---|
| **Navidrome** | Lightweight, music-only, Subsonic API. **Recommended.** Huge client ecosystem. |
| Jellyfin | Full media server with music. Fine if you already run it. Music metadata handling is weaker. |
| Plex / Plexamp | Polished, but partly closed/cloud-dependent. Plex's old Google Assistant integration was discontinued. |
| Gonic, Airsonic-Advanced, Ampache, LMS | Other Subsonic-compatible or self-hosted options. |

### Getting audio onto the Nest speakers

| Tool | Type | Notes |
|---|---|---|
| **Music Assistant** (with Home Assistant, or standalone) | Server-side player hub | Pulls from Navidrome/Jellyfin/Plex/local files/Subsonic. Plays to Chromecast/Nest (incl. speaker groups), Sonos, AirPlay, DLNA, Snapcast. Queues, radio mode, web UI. **Recommended.** |
| Symfonium (Android) | Phone app | Excellent Subsonic/Jellyfin client with first-class Chromecast casting. |
| Jellyfin web / Finamp / Feishin / Substreamer | Clients | Cast support varies. |
| `catt`, `pychromecast` | CLI / library | Good for scripting. |

### Voice control: realistic options, best first

1. **Google Home routines → Home Assistant scripts** (keeps "Hey Google").
   Home Assistant's Google Assistant integration (Nabu Casa Cloud, or the free manual setup) exposes HA **scripts as scenes** in Google Home. A Google Home routine with a custom starter phrase ("Hey Google, play my jazz playlist") can activate that scene. The HA script then tells Music Assistant to play the playlist on the right speaker.
   *Limit:* only fixed phrases, one per playlist/artist/station. There's no free-form search. That's why `tools/gen_voice_routines.py` exists: it generates the scripts and routines for you.
2. **Home Assistant Assist** (free-form). Music Assistant ships voice intents, so "play Radiohead in the kitchen" works with full search over your library. It needs an Assist voice device (e.g. Home Assistant Voice PE, an ESPHome satellite, or the HA phone app). Your Nest speakers stay as the *output*, not the microphone.
3. **Phone/UI casting**: Symfonium or the Music Assistant UI. No voice, but zero friction.

### Remote / VPS hosting

Cast receivers fetch the stream URL themselves, so the speaker must be able to reach it.
- **Library on a VPS, Music Assistant at home:** Music Assistant proxies/streams to the speakers on the LAN. This works fine. Put Navidrome behind HTTPS (Caddy/Traefik) or reach it over Tailscale/WireGuard.
- **Music Assistant on a VPS:** doesn't work. Cast discovery is mDNS on the local network. Keep the player hub on the LAN (a Raspberry Pi 4/5 or any small box is enough).

## Sources

- Google Media Actions docs: https://developers.google.cn/actions/media?hl=en
- Android "Google Assistant and media apps": https://developer.android.com/media/implement/assistant
- Music Assistant 2.0 announcement: https://www.music-assistant.io/blog/2024/05/09/music-assistant-2/
- HA community: Plex/Jellyfin + Google Home: https://community.home-assistant.io/t/home-assistant-with-plex-or-jellyfin-and-google-home-to-play-music-from-nas/960431
- Google Home: playing audio on Cast devices: https://support.google.com/googlehome/answer/7030086
- Gemini Spotify integration coverage: https://routenote.com/blog/google-gemini-gets-spotify-integration/
