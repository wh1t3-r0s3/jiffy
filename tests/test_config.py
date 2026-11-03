import json

from jiffy import config
from jiffy.config import Config


def test_missing_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "nope.json") == Config()


def test_garbage_file_gives_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    assert config.load(path) == Config()
    path.write_text("[1, 2]")
    assert config.load(path) == Config()


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(shortcut="<Super>g", format="mp4", quality="sharp", start_delay=3, after_save="folder")
    config.save(cfg, path)
    assert config.load(path) == cfg
    assert not path.with_suffix(".json.tmp").exists()


def test_bad_values_are_clamped_or_reset(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"start_delay": 500, "max_seconds": -4, "format": "webm", "quality": "ultra",
                                "show_cursor": "yes", "unknown": 1}))
    cfg = config.load(path)
    assert cfg.start_delay == 30
    assert cfg.max_seconds == 0
    assert cfg.quality == "balanced"
    assert cfg.format == "gif"
    assert cfg.show_cursor is True


def test_output_dir_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.output_dir(Config(output_dir="~/clips")) == tmp_path / "clips"
