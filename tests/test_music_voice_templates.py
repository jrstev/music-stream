"""Render the music scripts' templates and the shared macros with Jinja2.

Home Assistant renders each script variable to text, then parses it back into
Python types (lists/dicts/bools). We mimic that with ast.literal_eval, load
custom_templates/music_voice.jinja the way HA does (`{% from ... import ... %}`),
and stub the HA-only filters used (`bool`, `regex_replace`). Music Assistant
search responses and to-do lists are faked.

Skipped unless `jinja2` and `pyyaml` are installed.
"""
import ast
import re
import unittest
from pathlib import Path

try:
    import jinja2
    import jinja2.sandbox
    import yaml
except ImportError:  # pragma: no cover
    jinja2 = None

HA = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant"
PACKAGE = HA / "packages" / "music_voice.yaml"
TEMPLATES = HA / "custom_templates"
TODO = "todo.blocked_songs"


def native(text):
    text = text.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def track(name, artist, uri=None, album=None):
    item = {"name": name, "uri": uri or f"library://track/{name}", "artists": [{"name": artist}]}
    if album:
        item["album"] = {"name": album}
    return item


def todo(*entries):
    """entries: (title, artist) or (title, artist, status)"""
    items = []
    for e in entries:
        title, artist, status = (e + ("needs_action",))[:3]
        item = {"summary": title, "uid": title, "status": status}
        if artist:
            item["description"] = artist
        items.append(item)
    return {TODO: {"items": items}}


def make_env():
    env = jinja2.sandbox.SandboxedEnvironment(loader=jinja2.FileSystemLoader(str(TEMPLATES)))
    env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes", "on")
    env.filters["regex_replace"] = lambda v, find="", replace="", ignorecase=False: re.sub(
        find, replace, str(v), flags=re.I if ignorecase else 0)
    return env


@unittest.skipIf(jinja2 is None, "jinja2/pyyaml not installed")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = make_env()
        pkg = yaml.safe_load(PACKAGE.read_text())
        cls.play = pkg["script"]["music_play_from_library"]["sequence"]
        cls.search = pkg["script"]["music_library_search"]["sequence"]

    def tpl(self, _template, **ctx):
        return native(self.env.from_string(str(_template)).render(**ctx))

    def macro(self, call, **ctx):
        name = call.split("(")[0]
        return self.tpl("{% from 'music_voice.jinja' import " + name + " %}{{ " + call + " }}", **ctx)

    def render_vars(self, step_vars, ctx, names):
        for name in names:
            ctx[name] = self.tpl(step_vars[name], **ctx)
        return ctx

    def step_with(self, steps, var):
        return next(s["variables"] for s in steps if "variables" in s and var in s["variables"])


class Macros(Base):
    def test_norm(self):
        for raw, want in [("Teardrop - 2006 Remaster", "teardrop"), ("Teardrop (Live)", "teardrop"),
                          ("  TEARDROP!! ", "teardrop"), ("Simon & Garfunkel", "simon & garfunkel"),
                          ("Stand by Me [Mono]", "stand by me"), (None, "")]:
            self.assertEqual(str(self.macro("norm(s)", s=raw)), want, raw)

    def test_blocklist_from_todo(self):
        resp = todo(("Teardrop", "Massive Attack"), ("*", "Nickelback"), ("Wonderwall", ""),
                    ("Old", "x", "completed"), ("*", ""))
        self.assertEqual(self.macro("blocklist_from_todo(r, e)", r=resp, e=TODO), [
            {"t": "teardrop", "a": "massive attack"},
            {"t": "*", "a": "nickelback"},
            {"t": "wonderwall", "a": ""},
        ])  # ticked-off items and a bare "*" (would block everything) are ignored

    def test_blocklist_tolerates_missing_list(self):
        self.assertEqual(self.macro("blocklist_from_todo(r, e)", r={}, e=TODO), [])
        self.assertEqual(self.macro("blocklist_from_todo(r, e)", r=None, e=TODO), [])

    def blocked(self, entries, title, artists):
        bl = self.macro("blocklist_from_todo(r, e)", r=todo(*entries), e=TODO)
        a = self.macro("is_blocked(bl, t, a)", bl=bl, t=title, a=artists) == "yes"
        b = self.macro("is_blocked_todo(r, e, t, a)", r=todo(*entries), e=TODO, t=title, a=artists) == "yes"
        self.assertEqual(a, b, "is_blocked and is_blocked_todo disagree")
        return a

    def test_is_blocked(self):
        entries = [("Teardrop", "Massive Attack"), ("*", "Nickelback"), ("Wonderwall", "")]
        self.assertTrue(self.blocked(entries, "Teardrop - 2006 Remaster", ["Massive Attack"]))
        self.assertFalse(self.blocked(entries, "Teardrop", ["Elliott Smith"]))       # other artist
        self.assertTrue(self.blocked(entries, "Photograph", ["Nickelback"]))         # whole artist
        self.assertTrue(self.blocked(entries, "", ["Nickelback"]))                   # artist/album request
        self.assertTrue(self.blocked(entries, "Wonderwall", ["Ryan Adams"]))         # title, any artist
        self.assertFalse(self.blocked(entries, "", ["Oasis"]))                       # title entry doesn't block albums
        self.assertFalse(self.blocked([], "Teardrop", ["Massive Attack"]))

    def test_source_name(self):
        for uri, want in [("spotify://track/1", "Spotify"), ("spotify--abc://track/1", "Spotify"),
                          ("library://track/1", "your library"), ("ytmusic://x", "YouTube Music"),
                          ("some_new_service://x", "Some New Service")]:
            self.assertEqual(self.macro("source_name(u)", u=uri), want)

    def test_select_best_skips_blocked_and_counts(self):
        bl = [{"t": "teardrop", "a": "massive attack"}]
        reading = {"name": "teardrop", "artist": "massive attack"}
        found = {"tracks": [track("Teardrop", "Massive Attack"), track("Teardrop", "Massive Attack", "uri:live")]}
        out = self.macro("select_best(s, 'track', bl)", s=[[reading, found]], bl=bl)
        self.assertEqual(out, {"item": None, "blocked": 2})

    def test_select_best_artist_filter(self):
        reading = {"name": "teardrop", "artist": "massive attack"}
        found = {"tracks": [track("Teardrop", "Elliott Smith"), track("Teardrop", "Massive Attack", "uri:ma")]}
        out = self.macro("select_best(s, 'track', [])", s=[[reading, found]])
        self.assertEqual(out["item"]["uri"], "uri:ma")
        self.assertEqual(out["blocked"], 0)

    def test_select_best_blocked_artist_request(self):
        bl = [{"t": "*", "a": "nickelback"}]
        out = self.macro("select_best(s, 'artist', bl)",
                         s=[[{"name": "nickelback", "artist": ""}, {"artists": [{"name": "Nickelback", "uri": "a"}]}]],
                         bl=bl)
        self.assertEqual(out, {"item": None, "blocked": 1})

    def test_alternatives_exclude_blocked(self):
        bl = [{"t": "teardrop", "a": "massive attack"}]
        found = {"tracks": [track("Teardrop", "Massive Attack"), track("Teardrops", "Womack & Womack")]}
        out = self.macro("alternatives(r, 'track', bl)", r=[found, found], bl=bl)
        self.assertEqual(out, [{"name": "Teardrops", "artist": "Womack & Womack"}])


class PlayScript(Base):
    """The play script's own templates (readings, picks, replies)."""

    def setup(self, **fields):
        ctx = dict(fields)
        return self.render_vars(self.play[0]["variables"], ctx,
                                ["allow_streaming", "q", "by", "kind", "src", "is_radio", "is_exact",
                                 "readings", "first", "second", "request_text"])

    def picks(self, ctx, lib=({}, {}), web=({}, {}), blocked=None):
        ctx = dict(ctx, blocked_items=todo(*(blocked or [])), blocklist_entity=TODO)
        self.render_vars(self.step_with(self.play, "blocklist"), ctx, ["blocklist"])
        ctx.update(lib_first=lib[0], lib_second=lib[1], web_first=web[0], web_second=web[1])
        self.render_vars(self.step_with(self.play, "lib_pick"), ctx, ["lib_pick", "lib_best", "lib_alternatives"])
        self.render_vars(self.step_with(self.play, "web_pick"), ctx, ["web_pick", "web_best"])
        return ctx

    # --- readings ---------------------------------------------------------
    def test_defaults(self):
        ctx = self.setup(query="x", media_type="")
        self.assertEqual((ctx["kind"], ctx["src"], ctx["is_radio"], ctx["allow_streaming"]),
                         ("track", "auto", False, True))

    def test_title_and_artist_readings(self):
        ctx = self.setup(query="teardrop", artist="massive attack", media_type="track")
        self.assertEqual(ctx["readings"], [{"name": "teardrop", "artist": "massive attack"},
                                           {"name": "teardrop by massive attack", "artist": ""}])
        self.assertEqual(ctx["request_text"], "teardrop by massive attack")

    def test_by_inside_single_query_is_split(self):
        ctx = self.setup(query="kid a by radiohead", media_type="album")
        self.assertEqual(ctx["first"], {"name": "kid a", "artist": "radiohead"})
        self.assertEqual(ctx["second"], {"name": "kid a by radiohead", "artist": ""})

    def test_exact_is_used_as_is(self):
        ctx = self.setup(query="Nightcall", artist="Kavinsky", media_type="track", exact=True)
        self.assertEqual(ctx["readings"], [{"name": "Nightcall", "artist": "Kavinsky"}])
        self.assertEqual(ctx["first"], ctx["second"])

    # --- library first, then streaming ---------------------------------------
    def test_library_hit_wins(self):
        ctx = self.setup(query="teardrop", artist="massive attack", exact=True)
        lib = {"tracks": [track("Teardrop", "Massive Attack", "library://track/7")]}
        web = {"tracks": [track("Teardrop", "Massive Attack", "spotify://track/x")]}
        out = self.picks(ctx, lib=(lib, lib), web=(web, web))
        self.assertEqual(out["lib_best"]["uri"], "library://track/7")

    def test_streaming_only_when_library_misses(self):
        ctx = self.setup(query="Nightcall", artist="Kavinsky", exact=True)
        web = {"tracks": [track("Nightcall", "Kavinsky", "spotify://track/n")]}
        out = self.picks(ctx, web=(web, web))
        self.assertIsNone(out["lib_best"])
        self.assertEqual(out["web_best"]["uri"], "spotify://track/n")

    def test_source_streaming_ignores_library(self):
        ctx = self.setup(query="teardrop", artist="massive attack", exact=True, source="streaming")
        lib = {"tracks": [track("Teardrop", "Massive Attack")]}
        out = self.picks(ctx, lib=(lib, lib))
        self.assertIsNone(out["lib_best"])

    def test_blocked_song_is_never_picked_anywhere(self):
        ctx = self.setup(query="teardrop", artist="massive attack", exact=True)
        lib = {"tracks": [track("Teardrop", "Massive Attack")]}
        web = {"tracks": [track("Teardrop - Remastered", "Massive Attack", "spotify://track/t")]}
        out = self.picks(ctx, lib=(lib, lib), web=(web, web), blocked=[("Teardrop", "Massive Attack")])
        self.assertIsNone(out["lib_best"])
        self.assertEqual(out["lib_pick"]["blocked"], 2)   # -> script answers "blocked", no streaming
        self.assertIsNone(out["web_best"])
        self.assertGreater(out["web_pick"]["blocked"], 0)

    def test_stand_by_me_fallback_reading(self):
        ctx = self.setup(query="stand", artist="me", media_type="track")
        out = self.picks(ctx, lib=({"tracks": [track("Stand", "R.E.M.")]},
                                   {"tracks": [track("Stand by Me", "Ben E. King", "uri:sbm")]}))
        self.assertEqual(out["lib_best"]["uri"], "uri:sbm")

    def test_nothing_found(self):
        ctx = self.setup(query="nonexistent")
        out = self.picks(ctx, lib=(None, None), web=(None, None))
        self.assertIsNone(out["lib_best"])
        self.assertIsNone(out["web_best"])
        self.assertEqual(out["lib_alternatives"], [])

    def test_streaming_reply_names_the_service(self):
        steps = self.play
        final = steps[-2]["variables"]   # variables before the last stop
        ctx = {"web_best": track("Nightcall", "Kavinsky", "spotify://track/n"), "kind": "track",
               "is_radio": False, "spoken_area": "kitchen", "player": "media_player.k"}
        self.render_vars(final, ctx, ["description", "from_where"])
        speech = self.tpl(final["result"]["speech"], **ctx)
        self.assertEqual(speech, "Playing Nightcall by Kavinsky from Spotify in the kitchen.")


class SearchTool(Base):
    """Output of script.music_library_search, which the AI reads."""

    def run_search(self, media_type, found, blocked=()):
        ctx = {"media_type": media_type, "found": found, "blocked_items": todo(*blocked),
               "blocklist_entity": TODO}
        ctx["kinds"] = self.tpl(self.search[0]["variables"]["kinds"], **ctx)
        return self.tpl(self.step_with(self.search, "result")["result"], **ctx)

    def test_compact_rows_for_all_kinds(self):
        found = {"tracks": [track("Nightcall", "Kavinsky", "spotify://t", album="OutRun")],
                 "artists": [{"name": "Kavinsky", "uri": "library://artist/1"}]}
        self.assertEqual(self.run_search("", found), {
            "tracks": [{"name": "Nightcall", "source": "Spotify", "artist": "Kavinsky", "album": "OutRun"}],
            "albums": [], "artists": [{"name": "Kavinsky", "source": "your library"}], "playlists": [],
        })

    def test_blocked_results_left_out(self):
        found = {"tracks": [track("Teardrop", "Massive Attack"), track("Angel", "Massive Attack")]}
        out = self.run_search("track", found, blocked=[("Teardrop", "Massive Attack")])
        self.assertEqual([r["name"] for r in out["tracks"]], ["Angel"])


if __name__ == "__main__":
    unittest.main()
