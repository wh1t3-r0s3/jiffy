"""Drive Jiffy like a user on a virtual X display and check what it produces."""

import time

import pytest

from .conftest import wait_for

pytestmark = pytest.mark.e2e


def start_selection(desktop):
    desktop.action("record")
    desktop.wait_window("Jiffy selector")
    time.sleep(0.2)


def test_drag_record_stop_makes_a_gif_of_the_region(desktop):
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.drag(80, 80, 421, 331)
    desktop.wait_window("Jiffy bar")
    for i in range(8):
        desktop.xdotool("mousemove", str(120 + i * 30), str(150 + (i % 3) * 40))
        time.sleep(0.2)
    desktop.action("record")
    gif = desktop.wait_output(count + 1)
    stream = desktop.probe(gif)
    assert gif.suffix == ".gif"
    assert (stream["width"], stream["height"]) == (342, 252)
    assert int(stream["nb_read_frames"]) >= 10
    desktop.wait_window("Jiffy bar", present=False)


def test_click_records_exactly_the_window_under_the_pointer(desktop):
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.xdotool("mousemove", "780", "560")
    time.sleep(0.2)
    desktop.xdotool("click", "1")
    desktop.wait_window("Jiffy bar")
    time.sleep(0.6)
    desktop.action("stop")
    stream = desktop.probe(desktop.wait_output(count + 1))
    assert (stream["width"], stream["height"]) == (200, 150)


def test_stopping_right_away_still_saves(desktop):
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.drag(900, 100, 1100, 300)
    desktop.wait_window("Jiffy bar")
    desktop.action("record")
    stream = desktop.probe(desktop.wait_output(count + 1))
    assert int(stream["nb_read_frames"]) >= 1


def test_cancel_saves_nothing_and_cleans_up(desktop):
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.drag(900, 100, 1100, 300)
    desktop.wait_window("Jiffy bar")
    time.sleep(0.5)
    desktop.action("cancel")
    desktop.wait_window("Jiffy bar", present=False)
    time.sleep(1)
    assert len(desktop.outputs()) == count
    assert not any((desktop.root / "cache" / "jiffy").glob("*"))


def test_escape_closes_the_selector(desktop):
    start_selection(desktop)
    desktop.xdotool("key", "Escape")
    desktop.wait_window("Jiffy selector", present=False)


def test_countdown_then_mp4_with_auto_stop(desktop):
    desktop.configure(format="mp4", start_delay=1, max_seconds=2)
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.drag(100, 600, 501, 801)
    desktop.wait_window("Jiffy countdown")
    mp4 = desktop.wait_output(count + 1)
    stream = desktop.probe(mp4)
    assert mp4.suffix == ".mp4"
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (402, 202)


def test_saved_file_is_on_the_clipboard_as_a_file(desktop):
    count = len(desktop.outputs())
    start_selection(desktop)
    desktop.drag(80, 80, 300, 300)
    desktop.wait_window("Jiffy bar")
    time.sleep(0.5)
    desktop.action("stop")
    saved = desktop.wait_output(count + 1)

    def clipboard_uri():
        out = desktop.run("xclip", "-o", "-selection", "clipboard", "-t", "text/uri-list").stdout
        return out if saved.name in out else ""
    assert wait_for(clipboard_uri).strip() == saved.as_uri()
    targets = desktop.run("xclip", "-o", "-selection", "clipboard", "-t", "TARGETS").stdout.split()
    assert "x-special/gnome-copied-files" in targets
