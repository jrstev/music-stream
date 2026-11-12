"""Load Home Assistant YAML in tests: resolves `!secret` from a test secrets dict."""
from pathlib import Path

import yaml

TEST_SECRETS = {
    "music_default_player": "media_player.kitchen_speaker",
    "music_allow_streaming": True,
    "music_speakers": ["media_player.kitchen_speaker", "media_player.living_room_speaker"],
}


class _Loader(yaml.SafeLoader):
    pass


def _secret(loader, node):
    name = loader.construct_scalar(node)
    if name not in TEST_SECRETS:
        raise KeyError(f"secret {name!r} is not defined (add it to TEST_SECRETS and the docs)")
    return TEST_SECRETS[name]


_Loader.add_constructor("!secret", _secret)


def load(path: Path):
    return yaml.load(Path(path).read_text(), Loader=_Loader)
