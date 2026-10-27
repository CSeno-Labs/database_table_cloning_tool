from __future__ import annotations

import os
import sys
from io import UnsupportedOperation
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from rich.cells import cell_len
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from .i18n import t


@dataclass(frozen=True)
class MenuOption:
    label: str
    value: Any
    description: str = ""


KeyReader = Callable[[], str]


MAX_VISIBLE_MENU_OPTIONS = 10


def menu_option_window(index: int, option_count: int, max_visible_options: int = MAX_VISIBLE_MENU_OPTIONS) -> tuple[int, int]:
    """Return the half-open option range that keeps the active cursor visible."""
    if option_count <= 0:
        return 0, 0
    visible = max(1, min(max_visible_options, option_count))
    cursor = max(0, min(index, option_count - 1))
    start = max(0, min(cursor - visible // 2, option_count - visible))
    return start, start + visible


def editable_input_text(value: str) -> Text:
    """Style the --like flag and unescaped wildcard operators as the user types."""
    rendered = Text()
    if not value.startswith("--like") or (len(value) > 6 and not value[6].isspace()):
        rendered.append(value)
        return rendered

    rendered.append("--like", style="bold cyan")
    escaped = False
    for char in value[6:]:
        if char in {"%", "_", "*"} and not escaped:
            rendered.append(char, style="bold magenta")
        else:
            rendered.append(char)
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    return rendered


def _draw_editable_input(prompt: str, characters: list[str], cursor: int) -> None:
    value = "".join(characters)
    terminal = bool(getattr(sys.stdout, "isatty", lambda: False)())
    sys.stdout.write("\r" + prompt)
    Console(file=sys.stdout, force_terminal=terminal, color_system="standard" if terminal else None).print(
        editable_input_text(value), end=""
    )
    sys.stdout.write("\x1b[K")
    tail_width = cell_len(value[cursor:])
    if tail_width:
        sys.stdout.write(f"\x1b[{tail_width}D")
    sys.stdout.flush()


def _word_left(value: str, cursor: int) -> int:
    while cursor > 0 and value[cursor - 1].isspace():
        cursor -= 1
    while cursor > 0 and not value[cursor - 1].isspace():
        cursor -= 1
    return cursor


def _word_right(value: str, cursor: int) -> int:
    while cursor < len(value) and not value[cursor].isspace():
        cursor += 1
    while cursor < len(value) and value[cursor].isspace():
        cursor += 1
    return cursor


def read_text_or_back(prompt: str, *, key_reader: KeyReader | None = None) -> str | None:
    """Read editable text in a TTY, returning None immediately for Esc."""
    supplied_reader = key_reader is not None
    key_reader = key_reader or read_key
    if not sys.stdin.isatty():
        value = input(prompt)
        return None if value == "\x1b" else value
    if not supplied_reader:
        try:
            sys.stdin.fileno()
        except (OSError, UnsupportedOperation):
            value = input(prompt)
            return None if value == "\x1b" else value
    characters: list[str] = []
    cursor = 0
    _draw_editable_input(prompt, characters, cursor)
    while True:
        key = key_reader()
        normalized = key.lower().replace("+", "_")
        if normalized in {"escape", "esc"}:
            print()
            return None
        if normalized in {"enter", "return"}:
            print()
            return "".join(characters)
        if normalized in {"home", "ctrl_home"}:
            cursor = 0
        elif normalized in {"end", "ctrl_end"}:
            cursor = len(characters)
        elif normalized in {"ctrl_left", "ctrl_fleft"}:
            cursor = _word_left("".join(characters), cursor)
        elif normalized in {"ctrl_right", "ctrl_fright"}:
            cursor = _word_right("".join(characters), cursor)
        elif normalized == "left":
            cursor = max(0, cursor - 1)
        elif normalized == "right":
            cursor = min(len(characters), cursor + 1)
        elif normalized == "backspace":
            if cursor > 0:
                cursor -= 1
                characters.pop(cursor)
        elif normalized == "delete":
            if cursor < len(characters):
                characters.pop(cursor)
        elif len(key) == 1 and key >= " ":
            characters.insert(cursor, key)
            cursor += 1
        else:
            continue
        _draw_editable_input(prompt, characters, cursor)


def apply_menu_key(index: int, key: str, options: list[MenuOption]) -> tuple[int, Any | None]:
    if not options:
        return 0, None
    key = key.lower()
    if key in {"\x03", "ctrl+c", "ctrl_c"}:
        raise KeyboardInterrupt
    if key in {"up", "k"}:
        return (index - 1) % len(options), None
    if key in {"down", "j"}:
        return (index + 1) % len(options), None
    if key in {"enter", "right"}:
        return index, options[index].value
    if key in {"escape", "left", "backspace"}:
        return index, "back"
    if key.isdigit():
        number = int(key)
        if 1 <= number <= len(options):
            return number - 1, options[number - 1].value
        if number == 0:
            return index, "back"
    return index, None


def read_key() -> str:
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == "\x1b":
            return "escape"
        if ch == "\b":
            return "backspace"
        if ch in {"\x00", "\xe0"}:
            code = msvcrt.getwch()
            return {
                "H": "up",
                "P": "down",
                "K": "left",
                "M": "right",
                "G": "home",
                "O": "end",
                "S": "delete",
                "s": "ctrl_left",
                "t": "ctrl_right",
            }.get(code, "")
        return ch

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == "\x7f":
            return "backspace"
        if ch == "\x1b":
            if not select.select([fd], [], [], 0.04)[0]:
                return "escape"
            first = os.read(fd, 1).decode(errors="ignore")
            if first == "O":
                if not select.select([fd], [], [], 0.04)[0]:
                    return "escape"
                return decode_ansi_key("O" + os.read(fd, 1).decode(errors="ignore"))
            if first != "[":
                return "escape"
            seq = "["
            while True:
                if not select.select([fd], [], [], 0.04)[0]:
                    return "escape"
                next_char = os.read(fd, 1).decode(errors="ignore")
                seq += next_char
                if "@" <= next_char <= "~":
                    break
            return decode_ansi_key(seq)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def decode_ansi_key(sequence: str) -> str:
    return {
        "[A": "up", "[B": "down", "[D": "left", "[C": "right",
        "[H": "home", "[F": "end", "[1~": "home", "[4~": "end",
        "[3~": "delete", "[1;5D": "ctrl_left", "[1;5C": "ctrl_right",
        "[1;5H": "ctrl_home", "[1;5F": "ctrl_end", "[5D": "ctrl_left", "[5C": "ctrl_right",
        "OH": "home", "OF": "end",
    }.get(sequence, "escape")


def menu_renderable(title: str, option_list: list[MenuOption], index: int, footer: str = "", *, compact: bool = False) -> Group:
    lines = [
        Text(title, style="bold"),
        Text(t("menu.navigation") + "\n"),
    ]
    start, end = menu_option_window(index, len(option_list))
    if start:
        lines.append(Text(t("menu.more_above"), style="dim"))
    for idx in range(start, end):
        option = option_list[idx]
        marker = "➤" if idx == index else " "
        style = "reverse bold" if idx == index else ""
        lines.append(Text(f"{marker} {idx + 1}. {option.label}", style=style))
        if option.description:
            lines.append(Text(f"      ┗> {option.description}", style="dim"))
        if idx < end - 1 and not compact:
            lines.append(Text(""))
    if end < len(option_list):
        lines.append(Text(t("menu.more_below"), style="dim"))
    if footer:
        lines.append(Text(""))
        lines.append(Text(footer, style="dim"))
    return Group(*lines)


def print_menu(console: Console, title: str, option_list: list[MenuOption], index: int, footer: str = "", *, compact: bool = False) -> None:
    console.print(f"[bold]{title}[/]")
    console.print(t("menu.navigation") + "\n")
    start, end = menu_option_window(index, len(option_list))
    if start:
        console.print(f"[dim]{t('menu.more_above')}[/]")
    for idx in range(start, end):
        option = option_list[idx]
        marker = "➤" if idx == index else " "
        style = "reverse bold" if idx == index else ""
        console.print(f"{marker} {idx + 1}. {option.label}", style=style)
        if option.description:
            console.print(f"      ┗> {option.description}", style="dim")
        if idx < end - 1 and not compact:
            console.print()
    if end < len(option_list):
        console.print(f"[dim]{t('menu.more_below')}[/]")
    if footer:
        console.print(f"\n[dim]{footer}[/]")


def select_option(
    title: str,
    options: Iterable[MenuOption],
    *,
    default_index: int = 0,
    console: Console | None = None,
    key_reader: KeyReader = read_key,
    footer: str = "",
    hotkeys: dict[str, Any] | None = None,
    compact: bool = False,
) -> Any:
    console = console or Console()
    hotkeys = {key.lower(): value for key, value in (hotkeys or {}).items()}
    option_list = list(options)
    if not option_list:
        return None

    if not sys.stdin.isatty():
        console.print(f"\n[bold]{title}[/]")
        for idx, option in enumerate(option_list, 1):
            suffix = f" — {option.description}" if option.description else ""
            console.print(f"[{idx}] {option.label}{suffix}")
        if footer:
            console.print(f"\n[dim]{footer}[/]")
        console.print(f"[0] {t('menu.back_numbered')}")
        value = input(t("menu.choose")).strip()
        if value.lower() in hotkeys:
            return hotkeys[value.lower()]
        if not value:
            return option_list[default_index].value
        _, selected = apply_menu_key(default_index, value, option_list)
        return selected if selected is not None else "back"

    index = max(0, min(default_index, len(option_list) - 1))
    if not getattr(console, "is_terminal", False):
        while True:
            print_menu(console, title, option_list, index, footer, compact=compact)
            key = key_reader()
            if key.lower() in hotkeys:
                return hotkeys[key.lower()]
            index, selected = apply_menu_key(index, key, option_list)
            if selected is not None:
                return selected

    with Live(
        menu_renderable(title, option_list, index, footer, compact=compact),
        console=console,
        screen=True,
        transient=False,
        refresh_per_second=60,
    ) as live:
        while True:
            key = key_reader()
            if key.lower() in hotkeys:
                return hotkeys[key.lower()]
            index, selected = apply_menu_key(index, key, option_list)
            if selected is not None:
                return selected
            live.update(menu_renderable(title, option_list, index, footer, compact=compact), refresh=True)
