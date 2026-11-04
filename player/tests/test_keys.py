from pioneercd.keys import COMBO, HOLD, Keys


def run(steps):
    k, out = Keys(), []
    for t, pressed in steps:
        out += k.feed(set(pressed), t)
    return out


def test_tap_center():
    assert run([(0, ["center"]), (0.1, [])]) == ["center"]


def test_hold_center_goes_home_once():
    assert run([(0, ["center"]), (HOLD, ["center"]), (HOLD + 0.5, ["center"]), (2, [])]) == ["home"]


def test_a_alone_waits_then_raises():
    assert run([(0, ["A"]), (COMBO, ["A"]), (COMBO + 0.05, [])]) == ["vol_up"]


def test_quick_tap_of_b_still_counts():
    assert run([(0, ["B"]), (0.05, [])]) == ["vol_down"]


def test_a_and_b_together_mute_without_volume():
    assert run([(0, ["A"]), (0.05, ["A", "B"]), (0.6, ["A", "B"]), (0.7, ["B"]), (0.8, [])]) == ["mute"]


def test_down_repeats_while_held():
    assert run([(0, ["down"]), (0.3, ["down"]), (0.41, ["down"]), (0.57, ["down"]), (0.6, [])]) == ["down"] * 3


def test_left_once():
    assert run([(0, ["left"]), (1, ["left"]), (1.1, [])]) == ["left"]


def test_long_hold_goes_fast():
    steps = [(0, ["down"])] + [(0.4 + 0.15 * i, ["down"]) for i in range(10)] + [(2.0, ["down"]), (2.5, [])]
    out = run(steps)
    assert out[0] == "down" and out[-1] == "down_fast"
