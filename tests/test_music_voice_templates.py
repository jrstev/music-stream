"""Render the intent_script's selection templates with Jinja2 and fake search results.

Home Assistant renders each variable to text, then parses it back into Python
types (lists/dicts/bools). We mimic that with ast.literal_eval. HA-only
helpers (area_entities, config_entry_id, ...) aren't needed by the templates
tested here.

Skipped unless `jinja2` and `pyyaml` are installed.
"""
import ast
import unittest
from pathlib import Path

try:
    import jinja2
    import jinja2.sandbox
    import yaml
except ImportError:  # pragma: no cover
    jinja2 = None

PACKAGE = Path(__file__).resolve().parents[1] / "deploy" / "homeassistant" / "packages" / "music_voice.yaml"


def native(text):
    text = text.strip()
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def track(name, artist, uri=None):
    return {"name": name, "uri": uri or f"library://track/{name}", "artists": [{"name": artist}]}


@unittest.skipIf(jinja2 is None, "jinja2/pyyaml not installed")
class SelectionTemplates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scripts = yaml.safe_load(PACKAGE.read_text())["script"]
        steps = scripts["music_play_from_library"]["sequence"]
        cls.setup_vars = steps[0]["variables"]
        cls.pick_vars = next(s["variables"] for s in steps if "variables" in s and "best" in s["variables"])
        search_steps = scripts["music_library_search"]["sequence"]
        cls.search_vars = search_steps[0]["variables"]
        cls.search_result = search_steps[-2]["variables"]
        cls.env = jinja2.sandbox.SandboxedEnvironment()
        # Home Assistant's `bool` filter (simplified).
        cls.env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes", "on")

    def render(self, templates, ctx, names):
        for name in names:
            ctx[name] = native(self.env.from_string(str(templates[name])).render(**ctx))
        return ctx

    def readings(self, **slots):
        ctx = dict(slots)
        return self.render(self.setup_vars, ctx, ["q", "by", "kind", "is_radio", "is_exact", "readings", "first", "second"])

    def pick(self, ctx, found_first, found_second):
        ctx = dict(ctx, found_first=found_first, found_second=found_second)
        return self.render(self.pick_vars, ctx, ["best", "best_artist", "description", "alternatives"])

    # --- readings ----------------------------------------------------------
    def test_title_and_artist(self):
        ctx = self.readings(query="teardrop", artist="massive attack", media_type="track")
        self.assertEqual(ctx["readings"], [{"name": "teardrop", "artist": "massive attack"},
                                           {"name": "teardrop by massive attack", "artist": ""}])

    def test_by_inside_single_query_is_split(self):
        ctx = self.readings(query="kid a by radiohead", media_type="album")
        self.assertEqual(ctx["first"], {"name": "kid a", "artist": "radiohead"})
        self.assertEqual(ctx["second"], {"name": "kid a by radiohead", "artist": ""})

    def test_exact_title_is_not_split(self):
        ctx = self.readings(query="stand by me", media_type="track", exact=True)
        self.assertEqual(ctx["readings"], [{"name": "stand by me", "artist": ""}])
        self.assertEqual(ctx["first"], ctx["second"])

    def test_ai_call_with_separated_fields_is_used_as_is(self):
        # An AI caller passes title and artist separately with exact=true.
        ctx = self.readings(query="Nightcall", artist="Kavinsky", media_type="track", exact=True)
        self.assertEqual(ctx["readings"], [{"name": "Nightcall", "artist": "Kavinsky"}])

    def test_empty_media_type_defaults_to_track(self):
        ctx = self.readings(query="x", media_type="")
        self.assertEqual(ctx["kind"], "track")
        self.assertIs(ctx["is_radio"], False)

    def test_artist_queries_are_not_split(self):
        ctx = self.readings(query="belle and sebastian", media_type="artist")
        self.assertEqual(ctx["readings"], [{"name": "belle and sebastian", "artist": ""}])

    # --- picking -------------------------------------------------------------
    def test_artist_filter_skips_wrong_artist(self):
        ctx = self.readings(query="teardrop", artist="massive attack", media_type="track")
        found = {"tracks": [track("Teardrop", "Elliott Smith"), track("Teardrop", "Massive Attack", "uri:ma")]}
        out = self.pick(ctx, found, {"tracks": []})
        self.assertEqual(out["best"]["uri"], "uri:ma")
        self.assertEqual(out["description"], "Teardrop by Massive Attack")

    def test_falls_back_to_whole_phrase_as_title(self):
        # "play stand by me" -> title "stand" by "me" finds nothing by "me"
        ctx = self.readings(query="stand", artist="me", media_type="track")
        out = self.pick(ctx,
                        {"tracks": [track("Stand", "R.E.M.")]},
                        {"tracks": [track("Stand by Me", "Ben E. King", "uri:sbm")]})
        self.assertEqual(out["best"]["uri"], "uri:sbm")
        self.assertEqual(out["description"], "Stand by Me by Ben E. King")

    def test_nothing_found(self):
        ctx = self.readings(query="nonexistent", media_type="track")
        out = self.pick(ctx, {"tracks": []}, {})
        self.assertIsNone(out["best"])
        self.assertEqual(out["description"], "")
        self.assertEqual(out["alternatives"], [])

    def test_alternatives_offered_when_artist_does_not_match(self):
        ctx = self.readings(query="teardrop", artist="massive atack", media_type="track", exact=True)
        found = {"tracks": [track("Teardrop", "Massive Attack"), track("Teardrops", "Womack & Womack")]}
        out = self.pick(ctx, found, found)
        self.assertIsNone(out["best"])
        self.assertEqual(out["alternatives"], [{"name": "Teardrop", "artist": "Massive Attack"},
                                               {"name": "Teardrops", "artist": "Womack & Womack"}])

    def test_failed_search_is_tolerated(self):
        ctx = self.readings(query="anything", media_type="track")
        out = self.pick(ctx, None, None)
        self.assertIsNone(out["best"])

    def test_playlist_description_has_no_artist(self):
        ctx = self.readings(query="chill", media_type="playlist")
        out = self.pick(ctx, {"playlists": [{"name": "Chill", "uri": "uri:p"}]}, {})
        self.assertEqual(out["description"], "Chill")


@unittest.skipIf(jinja2 is None, "jinja2/pyyaml not installed")
class SearchToolTemplates(unittest.TestCase):
    """Output of script.music_library_search, which the AI reads."""

    setUpClass = classmethod(SelectionTemplates.setUpClass.__func__)

    def run_search(self, media_type, found):
        ctx = {"media_type": media_type, "found": found}
        ctx["kinds"] = native(self.env.from_string(self.search_vars["kinds"]).render(**ctx))
        return native(self.env.from_string(self.search_result["result"]).render(**ctx))

    def test_compact_rows_for_all_kinds(self):
        found = {
            "tracks": [{"name": "Nightcall", "uri": "u", "artists": [{"name": "Kavinsky"}],
                        "album": {"name": "OutRun"}}],
            "artists": [{"name": "Kavinsky", "uri": "a"}],
        }
        out = self.run_search("", found)
        self.assertEqual(out, {
            "tracks": [{"name": "Nightcall", "artist": "Kavinsky", "album": "OutRun"}],
            "albums": [], "artists": [{"name": "Kavinsky"}], "playlists": [],
        })

    def test_single_kind(self):
        out = self.run_search("album", {"albums": [{"name": "OutRun", "artists": [{"name": "Kavinsky"}]}]})
        self.assertEqual(out, {"albums": [{"name": "OutRun", "artist": "Kavinsky"}]})


if __name__ == "__main__":
    unittest.main()
