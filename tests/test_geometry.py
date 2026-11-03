from jiffy.geometry import Rect, place_beside

SCREEN = Rect(0, 0, 1920, 1080)


def test_from_corners_includes_both_corners_in_any_order():
    assert Rect.from_corners(10, 20, 13, 25) == Rect(10, 20, 4, 6)
    assert Rect.from_corners(13, 25, 10, 20) == Rect(10, 20, 4, 6)


def test_intersection_and_clipping():
    assert Rect(0, 0, 10, 10).intersection(Rect(5, 5, 10, 10)) == Rect(5, 5, 5, 5)
    assert Rect(0, 0, 10, 10).intersection(Rect(10, 0, 5, 5)) is None


def test_scaled_round_trips_on_hidpi():
    r = Rect(10, 20, 301, 151)
    assert r.scaled(2) == Rect(20, 40, 602, 302)
    assert r.scaled(2).scaled(0.5) == r


def test_bar_goes_below_the_region_right_aligned():
    x, y = place_beside(Rect(100, 100, 400, 300), (180, 36), [SCREEN], gap=8)
    assert (x, y) == (500 - 180, 400 + 8)


def test_bar_goes_above_when_the_region_touches_the_bottom():
    x, y = place_beside(Rect(100, 700, 400, 380), (180, 36), [SCREEN], gap=8)
    assert y == 700 - 36 - 8


def test_bar_stays_on_screen_for_a_region_at_the_left_edge():
    x, _ = place_beside(Rect(0, 100, 50, 300), (180, 36), [SCREEN], gap=8)
    assert x == 0


def test_fullscreen_region_puts_the_bar_on_another_monitor():
    second = Rect(1920, 0, 1920, 1080)
    x, y = place_beside(SCREEN, (180, 36), [SCREEN, second], gap=8)
    assert second.contains_rect(Rect(x, y, 180, 36))


def test_fullscreen_on_a_single_monitor_falls_back_inside_the_corner():
    x, y = place_beside(SCREEN, (180, 36), [SCREEN], gap=8)
    assert SCREEN.contains_rect(Rect(x, y, 180, 36))
