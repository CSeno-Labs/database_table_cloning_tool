from syncdb.interactive import MenuOption, apply_menu_key


def test_apply_menu_key_wraps_with_arrows():
    options = [MenuOption("A", "a"), MenuOption("B", "b"), MenuOption("C", "c")]

    assert apply_menu_key(0, "up", options) == (2, None)
    assert apply_menu_key(2, "down", options) == (0, None)


def test_apply_menu_key_selects_enter_and_goes_back():
    options = [MenuOption("A", "a"), MenuOption("Voltar", "back")]

    assert apply_menu_key(0, "enter", options) == (0, "a")
    assert apply_menu_key(0, "escape", options) == (0, "back")
    assert apply_menu_key(1, "left", options) == (1, "back")


def test_apply_menu_key_accepts_number_shortcut():
    options = [MenuOption("A", "a"), MenuOption("B", "b")]

    assert apply_menu_key(0, "2", options) == (1, "b")
