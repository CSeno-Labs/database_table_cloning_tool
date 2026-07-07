from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text


@dataclass(frozen=True)
class MenuOption:
    label: str
    value: Any
    description: str = ""


KeyReader = Callable[[], str]


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


def menu_renderable(title: str, option_list: list[MenuOption], index: int, footer: str = "") -> Group:
    lines = [
        Text(title, style="bold"),
        Text("Use ↑/↓ para navegar, Enter para selecionar, Esc/← para voltar. Números também funcionam.\n"),
    ]
    for idx, option in enumerate(option_list):
        marker = "➤" if idx == index else " "
        style = "reverse bold" if idx == index else ""
        lines.append(Text(f"{marker} {idx + 1}. {option.label}", style=style))
        if option.description:
            lines.append(Text(f"      ┗> {option.description}"))
            lines.append(Text(""))
    if footer:
        lines.append(Text(""))
        lines.append(Text(footer, style="dim"))
    return Group(*lines)


def print_menu(console: Console, title: str, option_list: list[MenuOption], index: int, footer: str = "") -> None:
    console.print(f"[bold]{title}[/]")
    console.print("Use ↑/↓ para navegar, Enter para selecionar, Esc/← para voltar. Números também funcionam.\n")
    for idx, option in enumerate(option_list):
        marker = "➤" if idx == index else " "
        style = "reverse bold" if idx == index else ""
        console.print(f"{marker} {idx + 1}. {option.label}", style=style)
        if option.description:
            console.print(f"      ┗> {option.description}")
            console.print()
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
) -> Any:
    console = console or Console()
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
        console.print("[0] Voltar")
        value = input("Escolha: ").strip()
        if not value:
            return option_list[default_index].value
        _, selected = apply_menu_key(default_index, value, option_list)
        return selected if selected is not None else "back"

    index = max(0, min(default_index, len(option_list) - 1))
    if not getattr(console, "is_terminal", False):
        while True:
            print_menu(console, title, option_list, index, footer)
            key = key_reader()
            index, selected = apply_menu_key(index, key, option_list)
            if selected is not None:
                return selected

    with Live(
        menu_renderable(title, option_list, index, footer),
        console=console,
        screen=True,
        transient=False,
        refresh_per_second=60,
    ) as live:
        while True:
            key = key_reader()
            index, selected = apply_menu_key(index, key, option_list)
            if selected is not None:
                return selected
            live.update(menu_renderable(title, option_list, index, footer), refresh=True)
