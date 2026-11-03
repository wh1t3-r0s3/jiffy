from jiffy import quality


def test_every_format_has_every_level():
    for fmt in ("gif", "mp4"):
        for level in quality.LEVELS:
            assert (fmt, level) in quality.PRESETS


def test_levels_get_better_in_order():
    for fmt in ("gif", "mp4"):
        fps = [quality.preset(fmt, level).fps for level in quality.LEVELS]
        assert fps == sorted(fps)


def test_unknown_values_fall_back_to_balanced_gif():
    assert quality.preset("webm", "ultra") == quality.preset("gif", "balanced")


def test_description_is_human():
    assert quality.describe("gif", "balanced") == "15 fps · up to 1280 px wide"
    assert quality.describe("gif", "small") == "10 fps · up to 720 px wide · 128 colours"
    assert quality.describe("mp4", "sharp") == "60 fps · full size"
