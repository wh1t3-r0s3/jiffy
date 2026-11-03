from pathlib import Path

from jiffy import ffmpeg
from jiffy.geometry import Rect


def test_capture_targets_the_region_with_cursor_and_limit():
    cmd = ffmpeg.capture_cmd(":0", Rect(10, 20, 301, 151), 15, True, Path("/w/c.mkv"), 60)
    assert cmd[cmd.index("-i") + 1] == ":0+10,20"
    assert cmd[cmd.index("-video_size") + 1] == "301x151"
    assert cmd[cmd.index("-draw_mouse") + 1] == "1"
    assert cmd[cmd.index("-t") + 1] == "60"
    assert "-progress" in cmd


def test_capture_without_limit_still_has_a_ceiling():
    cmd = ffmpeg.capture_cmd(":0", Rect(0, 0, 10, 10), 15, False, Path("c.mkv"), 0)
    assert cmd[cmd.index("-t") + 1] == str(ffmpeg.CAPTURE_CEILING_SECONDS)
    assert cmd[cmd.index("-draw_mouse") + 1] == "0"


def test_video_filter_downscales_only_when_wider():
    assert ffmpeg.video_filter(15, 800, 0) == "fps=15"
    assert ffmpeg.video_filter(15, 800, 1000) == "fps=15"
    assert ffmpeg.video_filter(15, 800, 640) == "fps=15,scale=640:-1:flags=lanczos"


def test_mp4_sizes_are_even():
    assert ffmpeg.video_filter(15, 801, 0, even=True) == "fps=15,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    assert "scale=640:-2" in ffmpeg.video_filter(15, 801, 640, even=True)


def test_encoders_read_only_the_recorded_time():
    for cmd in (ffmpeg.gif_palette_cmd(Path("c.mkv"), 2.5, Path("p.png"), "fps=15", 256),
                ffmpeg.gif_encode_cmd(Path("c.mkv"), 2.5, Path("p.png"), Path("o.gif"), "fps=15", "bayer"),
                ffmpeg.mp4_encode_cmd(Path("c.mkv"), 2.5, Path("o.mp4"), "fps=15", 23)):
        assert cmd[cmd.index("-t") + 1] == "2.500"
        assert cmd.index("-t") < cmd.index("-i")


def test_progress_parsing():
    assert ffmpeg.parse_progress_seconds("out_time_us=1500000") == 1.5
    assert ffmpeg.parse_progress_seconds("out_time_ms=-5") == 0
    assert ffmpeg.parse_progress_seconds("frame=10") is None
    assert ffmpeg.parse_progress_seconds("out_time_us=N/A") is None
    assert ffmpeg.frame_count("frame=12") == 12
    assert ffmpeg.frame_count("fps=12") is None


def test_quality_knobs_reach_the_encoders():
    assert "max_colors=128" in " ".join(ffmpeg.gif_palette_cmd(Path("c"), 1, Path("p"), "fps=10", 128))
    assert "dither=sierra2_4a" in " ".join(ffmpeg.gif_encode_cmd(Path("c"), 1, Path("p"), Path("o"), "f", "sierra2_4a"))
    cmd = ffmpeg.mp4_encode_cmd(Path("c"), 1, Path("o"), "f", 18)
    assert cmd[cmd.index("-crf") + 1] == "18"
