from syncdb.interactive import MenuOption, apply_menu_key, select_option


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


def test_ctrl_c_character_raises_keyboard_interrupt():
    options = [MenuOption("A", "a")]

    try:
        apply_menu_key(0, "\x03", options)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Ctrl+C character should raise KeyboardInterrupt")


def test_sync_context_text_matches_step_labels():
    from syncdb.cli import format_sync_context

    assert format_sync_context(step="origin") == "Escolha o banco de origem"
    assert format_sync_context(origin="prod", step="destination") == "Origem escolhida: prod\nEscolha o banco de destino"
    assert format_sync_context(origin="prod", destination="local", step="tables") == (
        "Origem escolhida: prod\nDestino escolhido: local\nEscolha as tabelas que serão sincronizadas"
    )
    assert format_sync_context(origin="prod", destination="local", tables=["periodo"], step="mode") == (
        "Origem escolhida: prod\nDestino escolhido: local\n"
        "Tabelas escolhidas: periodo\nEscolha o motor"
    )


def test_select_option_tty_prints_option_descriptions_under_each_item(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    selected = select_option(
        "Sincronização avançada",
        [MenuOption("Banco de origem", "origin", "prod (host/db)"), MenuOption("Voltar", "back")],
        key_reader=lambda: "enter",
    )

    shown = capsys.readouterr().out
    assert selected == "origin"
    assert "1. Banco de origem" in shown
    assert "┗> prod (host/db)" in shown
    assert "— prod (host/db)" not in shown


def test_select_option_tty_does_not_style_description_like_selected_item(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    calls = []

    class FakeConsole:
        def clear(self):
            calls.append(("clear", None, None))

        def print(self, text="", style=""):
            calls.append(("print", str(text), style))

    selected = select_option(
        "Menu",
        [MenuOption("Item", "item", "resposta"), MenuOption("Voltar", "back")],
        console=FakeConsole(),
        key_reader=lambda: "enter",
    )

    assert selected == "item"
    assert ("clear", None, None) not in calls
    assert ("print", "➤ 1. Item", "reverse bold") in calls
    assert ("print", "      ┗> resposta", "") in calls


def test_advanced_mode_options_allow_dump_only_without_partial_sync():
    from syncdb.cli import advanced_mode_options

    all_modes = [option.value for option in advanced_mode_options(where_clause="", insert_missing=False)]
    partial_modes = [option.value for option in advanced_mode_options(where_clause="ano >= 2026", insert_missing=False)]

    assert all_modes[:4] == ["auto", "managed-dump", "system-dump", "python"]
    assert partial_modes == ["python", "back"]


def test_select_option_non_tty_prints_context_footer(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")

    selected = select_option(
        "Sincronizar tabelas — escolha a origem",
        [MenuOption("prod", "prod")],
        footer="Tabelas escolhidas: periodo, aluno",
    )

    shown = capsys.readouterr().out
    assert selected == "prod"
    assert "Sincronizar tabelas" in shown
    assert "Tabelas escolhidas: periodo, aluno" in shown
