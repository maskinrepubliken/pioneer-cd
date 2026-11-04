from pioneercd.app import ListScreen


def screen(labels, sel):
    s = ListScreen("x", [{"label": label} for label in labels])
    s.sel = sel
    return s


def test_jump_down_to_next_letter():
    assert screen(["Abba", "Air", "Beck", "Bjork", "Cream"], 0).jump(1) == 2


def test_jump_up_to_start_of_letter_then_previous():
    s = screen(["Abba", "Air", "Beck", "Bjork", "Cream"], 3)
    assert s.jump(-1) == 2
    s.sel = 2
    assert s.jump(-1) == 0
