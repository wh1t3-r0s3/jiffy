from jiffy import shortcuts


def test_keeps_the_preferred_shortcut_when_free():
    assert shortcuts.choose("<Shift>Print", lambda accel: []) == "<Shift>Print"


def test_falls_back_to_the_first_free_candidate():
    taken = {"<Shift>Print", "<Super><Shift>Print"}
    assert shortcuts.choose("<Shift>Print", lambda a: ["x"] if a in taken else []) == "<Super><Shift>g"


def test_keeps_the_preferred_one_when_everything_is_taken():
    assert shortcuts.choose("<Shift>Print", lambda a: ["x"]) == "<Shift>Print"


def test_accelerators_compare_by_meaning_not_spelling():
    assert shortcuts.same_accel("<Shift>Print", "<Shift>Print")
    assert shortcuts.same_accel("<Control><Alt>g", "<Primary><Alt>G")
    assert not shortcuts.same_accel("<Shift>Print", "Print")
    assert not shortcuts.same_accel("", "")


def test_recognises_its_own_entries():
    assert shortcuts.is_ours(shortcuts.RECORD_COMMAND)
    assert shortcuts.is_ours("/usr/bin/jiffy record")
    assert not shortcuts.is_ours("flameshot gui")
    assert not shortcuts.is_ours("")
