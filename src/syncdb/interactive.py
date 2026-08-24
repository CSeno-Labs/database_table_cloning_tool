from __future__ import annotations

import os
import sys
from io import UnsupportedOperation
from dataclasses import dataclass
from typing import Any, Callable, Iterable

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
    print(prompt, end="", flush=True)
    characters: list[str] = []
    while True:
        key = key_reader()
        if key in {"escape", "left"}:
            print()
            return None
        if key == "enter":
            print()
            return "".join(characters)
        if key == "backspace":
            if characters:
                characters.pop()
                print("\b \b", end="", flush=True)
            continue
        if len(key) == 1 and key >= " ":
            characters.append(key)
            print(key, end="", flush=True)


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
            }.get(code, "")
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == "\x7f":
            return "backspace"
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            return {
                "[A": "up",
                "[B": "down",
                "[D": "left",
                "[C": "right",
            }.get(seq, "escape")
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
