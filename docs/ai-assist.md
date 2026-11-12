# AI interpretation of music requests

The fixed phrases in [voice-assist.md](voice-assist.md) need a fairly literal request ("play Teardrop by Massive Attack"). With an AI model as Assist's conversation agent, you can say what you'd say to a person:

| You say | The AI works out | Then |
|---|---|---|
| "play the song from Drive" | track **Nightcall**, artist **Kavinsky** | plays it |
| "put on that whistling Peter Bjorn song in the kitchen" | **Young Folks** by Peter Bjorn and John, area kitchen | plays it in the kitchen |
| "play massive attach teardrop" (misheard) | **Teardrop** by **Massive Attack** | plays it |
| "something mellow for cooking" | an artist that fits, e.g. Bonobo | checks it's in your library, plays it in radio mode |
| "play the new Radiohead album" | their latest album | searches your library, plays it if you have it |

## How it works

```
speech ─► whisper ─► AI conversation agent ──(tool call)──► script.music_play_from_library ─► Music Assistant ─► Nest
                         │   ▲                              (query, artist, media_type, area, radio, exact)
                         │   └── result: found / playing / alternatives
                         └──(tool call)──► script.music_library_search   (check what's in the library)
```

The AI never plays anything itself. It turns your request into structured fields and calls two Home Assistant scripts from `deploy/homeassistant/packages/music_voice.yaml`. Home Assistant offers every script exposed to Assist as a tool, with the script's field descriptions as the tool's parameters.
- **Play music from library:** searches the library and checks the artist. It plays the best match, or returns `found: false` plus close alternatives.
- **Search music library:** looks things up without playing, so the AI can check titles and spellings before retrying. It can include streaming services.
- **Block current song / Block song / Unblock song:** manage the blocklist, either for what's playing or by name.

The play script checks your library first, then Spotify (or whatever is connected in Music Assistant). It never returns blocked songs; a blocked request comes back as `blocked: true`, and the prompt tells the AI not to work around it. See [voice-assist.md → Spotify fallback and blocklist](voice-assist.md#spotify-fallback-and-blocklist).

The fixed-phrase intent from the non-AI setup calls the same play script, so both pipelines behave the same.

## Pick a model

Any Home Assistant conversation integration that supports tool calling ("Control Home Assistant") works. Two good options:

### Cloud: Anthropic (Claude)
- Fast on any hardware, and the best at the "song from that movie" kind of request.
- Needs an API key from the Anthropic Console. Costs are per request; a request is a few thousand input tokens, mostly HA's tool and entity descriptions, so expose only what the assistant needs.
- Models (set in the integration's options; untick "Recommended model settings" to choose):
  - **`claude-opus-5-5`**: the default recommendation, strongest at resolving vague requests ($4 / $20 per million input/output tokens).
  - **`claude-haiku-5-5`**: much cheaper ($0.10 / $0.50) and lower latency. Worth trying if Opus feels slow or you make lots of requests; it may be weaker on very indirect requests.

### Local: Ollama
- Free and private. Needs a decent machine: a GPU makes it comfortable, while CPU-only works but adds several seconds per reply.
- Start it with:
  ```sh
  cd deploy
  docker compose --profile ai-local up -d ollama
  docker exec ollama ollama pull qwen3:8b
  ```
- Use a model with tool-calling support. `qwen3:8b` is a reasonable default; bigger models are better at identifying obscure songs.
- A local model's music knowledge is far smaller than a cloud model's, so it will miss more "the song from …" requests. It still handles title/artist parsing and misheard names well.

## Setup

Do the [voice-assist.md](voice-assist.md) setup first (stack, whisper/piper, packages, areas). Then:

1. **Add the integration.** Go to Settings → Devices & services → Add integration:
   - **Anthropic**: paste the API key, then set the model in its options.
   - **Ollama**: URL `http://127.0.0.1:11434`, model `qwen3:8b`.
2. **Expose the music tools.** Settings → Voice assistants → *Expose* tab → add:
   - `script.music_play_from_library`
   - `script.music_library_search`
   - `script.music_block_current_song`
   - `script.music_block_song`
   - `script.music_unblock_song`

   Keep the exposed list short. Every exposed entity goes into the AI's context, which costs tokens and slows replies. The Music Assistant speakers themselves don't need to be exposed for music.
3. **Configure the agent.** In the integration's options (the conversation agent entry):
   - **Control Home Assistant / LLM API:** select **Assist**. This is what turns exposed scripts into tools.
   - **Instructions / prompt:** paste the contents of `deploy/homeassistant/ai_prompt.txt`, after any existing text.
4. **Create the assistant.** Settings → Voice assistants → Add assistant (e.g. "Music AI"):
   - Conversation agent: the Anthropic or Ollama agent
   - Speech-to-text: faster-whisper
   - Text-to-speech: piper
   - **"Prefer handling commands locally": OFF.** The local music sentences start with "play …" followed by a wildcard, so they'd match almost every music request and the AI would never see it. Turn it on only if you'd rather have fixed phrases handled instantly and offline, with the AI only for non-"play" requests.
5. **Use it.** Make it the preferred assistant, or assign it to your Voice PE. Test by typing in the Assist dialog first: `play the song from Drive`. The debug view (Voice assistants → ⋮ → Debug) shows each tool call and its result.

## Tips

- **Speed.** Most of the delay is the AI's two or three tool calls. A faster model or fewer exposed entities helps most.
- **Keep a non-AI fallback.** Leave the original local-only assistant configured. If the API is down or you're offline, switch the Voice PE back to it; the fixed phrases still work.
- **Wrong picks.** If the AI keeps choosing the wrong version of a song (live vs. studio, remasters), add a line to the prompt, e.g. "Prefer studio versions over live recordings unless asked."

## Status

The scripts' search/selection templates are unit-tested with fake search results (`tests/test_music_voice_templates.py`), including the AI-style calls (separated fields, `exact: true`) and the search tool's compact output.

Not yet verified against a live Home Assistant:
- how each conversation integration converts these script fields into tool parameters
- the real `music_assistant.search` response shape
- the end-to-end latency
