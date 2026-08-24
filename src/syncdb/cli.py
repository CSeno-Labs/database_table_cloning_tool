from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from .clients import find_managed_client, find_system_client, resolve_client
from .config import ConfigError, ensure_config, load_config, profile_tag, redact_config, resolve_profile_pair, save_config, sync_runtime_config
from .db import test_connection
from .engine import drop_table, normalize_where_clause, preflight_advanced_sync, run_dump_sync, run_python_advanced_sync, run_python_sync, run_table_backup
from .interactive import MenuOption, read_text_or_back, select_option
from .i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language, set_language, t
from .managed_client import ManagedClientError, install_managed_client, resolve_default_package
from .paths import AppPaths
from .schema import SchemaAction, SchemaDiff, SchemaPlan, _execution_statements, _operation_statements, build_schema_plan, compare_schema, describe_schema_action, execute_recreate_table, execute_schema_plan, inspect_schema_pair, normalize_schema_action
from .tables import parse_tables, parse_tables_file

console = Console()
APP_VERSION = "3.0.0"
MENU_BACK = -1000
PROJECT_REPO_URL = "https://github.com/CSeno-Labs/database_table_cloning_tool.git"


def is_menu_back(status: object) -> bool:
    return status == MENU_BACK


def sync_progress(total: int) -> Progress:
    return Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )


def _add_language_arguments(parser: argparse.ArgumentParser) -> None:
    """Accept --lang before or after any subcommand without changing config."""
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default=argparse.SUPPRESS, help=t("help.language"))
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _add_language_arguments(child)


def _language_override(argv: list[str]) -> str | None:
    for index, value in enumerate(argv):
        if value == "--lang" and index + 1 < len(argv):
            return normalize_language(argv[index + 1])
        if value.startswith("--lang="):
            return normalize_language(value.partition("=")[2])
    return None


def _paths_from_argv(argv: list[str]) -> AppPaths:
    """Resolve an explicit config path before constructing localized argparse."""
    config_value: str | None = None
    for index, value in enumerate(argv):
        if value == "--config" and index + 1 < len(argv):
            config_value = argv[index + 1]
            break
        if value.startswith("--config="):
            config_value = value.partition("=")[2]
            break
    if not config_value:
        return AppPaths.current()
    cfg_path = Path(config_value).expanduser().resolve()
    base_dir = cfg_path.parent.parent if cfg_path.parent.name == "config" else cfg_path.parent
    return AppPaths(config_dir=cfg_path.parent, data_dir=base_dir / "data", state_dir=base_dir / "state", cache_dir=base_dir / "cache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sync-db", description=t("app.description"))
    parser.add_argument("--version", action="store_true", help=t("help.version"))
    parser.add_argument("--config", help=t("help.config"))
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help=t("help.init"))
    init.add_argument("--quiet", action="store_true", help=t("help.quiet"))
    sub.add_parser("doctor", help=t("help.doctor"))
    update_app = sub.add_parser("update", help=t("help.update"))
    update_app.add_argument("--branch", default="main", help=argparse.SUPPRESS)
    update_app.add_argument("--repo-url", default=PROJECT_REPO_URL, help=argparse.SUPPRESS)

    sync = sub.add_parser("sync", help=t("help.sync"))
    add_table_args(sync)
    sync.add_argument("-o", "--origin", help=t("help.sync_origin"))
    sync.add_argument("-d", "--destination", help=t("help.sync_destination"))
    sync.add_argument("--last", action="store_true", help=t("help.last"))
    sync.add_argument("--mode", choices=["auto", "dump", "managed-dump", "system-dump", "python"], help=t("help.mode"))
    sync.add_argument("--where", help=t("help.where"))
    sync.add_argument("--insert-missing", action="store_true", help=t("help.insert_missing"))
    sync.add_argument("-y", "--yes", action="store_true", help=t("help.yes_sync"))
    sync.add_argument("--dry-run", action="store_true", help=t("help.dry_run"))
    sync.add_argument("--backup", nargs="?", const="temp", choices=["temp", "keep", "none"], help=t("help.backup_mode"))

    backup = sub.add_parser("backup", help=t("help.backup"))
    add_table_args(backup)
    backup.add_argument("-d", "--destination", help=t("help.backup_destination"))
    backup.add_argument("-y", "--yes", action="store_true", help=t("help.yes_backup"))

    schema = sub.add_parser("schema", help=t("help.schema"), description=t("help.schema"))
    schema_sub = schema.add_subparsers(dest="schema_command")
    plan = schema_sub.add_parser("plan", help=t("help.plan"), description=t("help.plan"))
    plan.add_argument("plan_action", choices=["copy", "update"], help=t("help.plan_action"))
    add_table_args(plan)
    plan.add_argument("-o", "--origin", help=t("help.origin"))
    plan.add_argument("-d", "--destination", help=t("help.destination"))
    plan.add_argument("--sql", action="store_true", help=t("help.sql"))
    plan.add_argument("--no-sql", action="store_true", help=t("help.no_sql"))
    plan.add_argument("--sql-only", action="store_true", help=t("help.sql_only"))
    plan.add_argument("--save", metavar="FILE.sql", help=t("help.save"))
    for name, help_text in (
        ("diff", t("help.schema.diff")),
        ("copy", t("help.schema.copy")),
        ("update", t("help.schema.update")),
        ("recreate-table", t("help.schema.recreate")),
    ):
        schema_cmd = schema_sub.add_parser(name, help=help_text, description=t("help.schema"))
        add_table_args(schema_cmd)
        schema_cmd.add_argument("-o", "--origin", help=t("help.origin"))
        schema_cmd.add_argument("-d", "--destination", help=t("help.destination"))
        if name in {"copy", "update"}:
            schema_cmd.add_argument("-y", "--yes", action="store_true", help=t("help.yes_schema"))
            schema_cmd.add_argument("--sql", action="store_true", help=t("help.sql"))
            schema_cmd.add_argument("--no-sql", action="store_true", help=t("help.no_sql"))
            schema_cmd.add_argument("--sql-only", action="store_true", help=t("help.sql_only"))
        if name == "recreate-table":
            schema_cmd.add_argument("-y", "--yes", action="store_true", help=t("help.recreate_yes"))
            schema_cmd.add_argument("--keep-backup", action="store_true", help=t("help.keep_backup"))
        if name == "diff":
            schema_cmd.add_argument("-v", "--verbose", action="store_true", help=t("help.verbose"))

    tables = sub.add_parser("tables", help=t("help.tables"))
    tables.add_argument("-t", "--tables", nargs="+", help=t("help.tables_inline"))
    tables.add_argument("-f", "--file", help=t("help.tables_file"))

    cfg = sub.add_parser("config", help=t("help.config_cmd"))
    cfg_sub = cfg.add_subparsers(dest="config_command")
    cfg_sub.add_parser("path", help=t("help.config.path"))
    cfg_sub.add_parser("show", help=t("help.config.show"))
    cfg_sub.add_parser("edit", help=t("help.config.edit"))
    cfg_sub.add_parser("remove", help=t("help.config.remove"))

    db = sub.add_parser("db", help=t("help.db"))
    db_sub = db.add_subparsers(dest="db_command")
    db_sub.add_parser("list", help=t("help.db.list"))
    add_db = db_sub.add_parser("add", help=t("help.db.add"))
    add_db.add_argument("tag", nargs="?", help=t("help.db.tag"))
    edit_db = db_sub.add_parser("edit", help=t("help.db.edit"))
    edit_db.add_argument("tag")
    rm_db = db_sub.add_parser("remove", help=t("help.db.remove"))
    rm_db.add_argument("tag")
    test_db = db_sub.add_parser("test", help=t("help.db.test"))
    test_db.add_argument("tag", nargs="?")
    defaults_db = db_sub.add_parser("set-defaults", help=t("help.db.defaults"))
    defaults_db.add_argument("-o", "--origin", required=True)
    defaults_db.add_argument("-d", "--destination", required=True)

    client = sub.add_parser("client", help=t("help.client"))
    client_sub = client.add_subparsers(dest="client_command")
    client_sub.add_parser("status", help=t("help.client.status"))
    client_sub.add_parser("path", help=t("help.client.path"))
    install = client_sub.add_parser("install", help=t("help.client.install"))
    add_client_install_args(install)
    client_sub.add_parser("remove", help=t("help.client.remove"))
    update = client_sub.add_parser("update", help=t("help.client.update"))
    add_client_install_args(update)

    logs = sub.add_parser("logs", help=t("help.logs"))
    logs_sub = logs.add_subparsers(dest="logs_command")
    logs_sub.add_parser("path", help=t("help.logs.path"))
    tail = logs_sub.add_parser("tail", help=t("help.logs.tail"))
    tail.add_argument("-n", "--lines", type=int, default=40, help=t("help.logs.lines"))
    logs_sub.add_parser("open", help=t("help.logs.open"))
    logs_sub.add_parser("clear", help=t("help.logs.clear"))

    uninstall = sub.add_parser("uninstall", help=t("help.uninstall"))
    uninstall.add_argument("--all", action="store_true", help=t("help.uninstall.all"))
    uninstall.add_argument("--keep-config", action="store_true", help=t("help.uninstall.keep_config"))
    _add_language_arguments(parser)
    return parser


def add_table_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-t", "--tables", nargs="+", help=t("help.tables_arg"))
    parser.add_argument("-f", "--file", help=t("help.file_arg"))


def add_client_install_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive-url", help=t("help.archive_url"))
    parser.add_argument("--sha256", help=t("help.sha256"))
    parser.add_argument("--yes", action="store_true", help=t("help.yes"))


def normalize_legacy_args(argv: list[str]) -> list[str]:
    """Support the old CLI shape: sync-db -t tabela, -s, -l.

    The new CLI is subcommand-based, but existing users naturally try the old
    flags. Normalize those flags before argparse sees a subcommand position.
    """
    commands = {"init", "doctor", "update", "sync", "backup", "schema", "tables", "config", "db", "client", "logs", "uninstall"}
    legacy_flags = {"-t", "--tables", "-f", "--file", "-o", "--origin", "-d", "--destination", "--where", "--insert-missing", "--dry-run", "-y", "--yes", "-s", "--showtables", "-l", "--logs"}
    if not any(arg in legacy_flags for arg in argv):
        return argv

    insert_at = 0
    while insert_at < len(argv):
        arg = argv[insert_at]
        if arg in commands:
            return argv
        if arg == "--config" and insert_at + 1 < len(argv):
            insert_at += 2
            continue
        if arg.startswith("--config="):
            insert_at += 1
            continue
        if arg.startswith("-"):
            break
        return argv

    command = "sync"
    normalized: list[str] = []
    for arg in argv:
        if arg in {"-s", "--showtables"}:
            command = "tables"
            continue
        if arg in {"-l", "--logs"}:
            command = "logs"
            continue
        normalized.append(arg)
    normalized.insert(insert_at, command)
    return normalized


def main(argv: list[str] | None = None) -> int:
    argv = normalize_legacy_args(list(argv) if argv is not None else sys.argv[1:])
    override = _language_override(argv)
    paths = _paths_from_argv(argv)
    set_language(DEFAULT_LANGUAGE)
    if override:
        set_language(override)
    elif paths.config_file.exists():
        try:
            set_language(load_config(paths).get("language"))
        except ConfigError:
            # Keep parser creation resilient; dispatch renders the normal config error.
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    args._language_override = override

    try:
        if args.version:
            console.print(f"sync-db {APP_VERSION}")
            return 0
        return dispatch(args, parser, paths)
    except KeyboardInterrupt:
        print_exit_banner()
        return 130
    except ConfigError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        console.print("Dica: rode `sync-db config path` e abra o arquivo no editor. Em JSON, barras invertidas precisam ser escapadas como `\\`.")
        return 2


def set_config_language(paths: AppPaths, config: dict, language: object) -> str:
    """Persist a validated interface language and make it active immediately."""
    selected = set_language(language)
    config["language"] = selected
    save_config(config, paths)
    console.print(f"[green]{t('language.saved', language=t('language.en' if selected == 'en' else 'language.pt'))}[/]")
    return selected


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, paths: AppPaths) -> int:
    override = getattr(args, "_language_override", None)
    if override:
        set_language(override)
    else:
        set_language(load_config(paths).get("language"))
    if not args.command:
        return run_interactive_menu(paths)
    if args.command == "init":
        return cmd_init(paths, quiet=getattr(args, "quiet", False))
    if args.command == "doctor":
        return cmd_doctor(paths)
    if args.command == "update":
        return cmd_update(args)
    if args.command == "sync":
        return cmd_sync(paths, args)
    if args.command == "backup":
        return cmd_backup(paths, args)
    if args.command == "schema":
        return cmd_schema(paths, args)
    if args.command == "tables":
        return cmd_tables(args)
    if args.command == "config":
        return cmd_config(paths, args)
    if args.command == "db":
        return cmd_db(paths, args)
    if args.command == "client":
        return cmd_client(paths, args)
    if args.command == "logs":
        return cmd_logs(paths, args)
    if args.command == "uninstall":
        return cmd_uninstall(paths, args)
    parser.error(f"Comando desconhecido: {args.command}")
    return 2


def print_exit_banner() -> None:
    if sys.stdin.isatty():
        console.clear()
    art = """
███████╗██╗   ██╗███╗   ██╗ ██████╗       ██████╗ ██████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝       ██╔══██╗██╔══██╗
███████╗ ╚████╔╝ ██╔██╗ ██║██║      █████╗██║  ██║██████╔╝
╚════██║  ╚██╔╝  ██║╚██╗██║██║      ╚════╝██║  ██║██╔══██╗
███████║   ██║   ██║ ╚████║╚██████╗       ██████╔╝██████╔╝
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝       ╚═════╝ ╚═════╝
""".strip("\n")
    console.print(Panel(f"[bold cyan]{art}[/]\n\n[bold]sync-db[/]\n[dim]{'by: SNeto99':>62}[/]", border_style="cyan"))


def cmd_init(paths: AppPaths, *, quiet: bool = False) -> int:
    path = ensure_config(paths)
    if not quiet:
        console.print(f"[green]Config pronto:[/] {path}")
        console.print("Edite esse arquivo e depois rode: sync-db doctor")
    return 0


def is_windows() -> bool:
    return os.name == "nt"


def find_running_sync_db_exe() -> str | None:
    """Return the path to the sync-db executable on Windows, or None on failure.

    Uses shutil.which so it resolves exactly the file the OS found in PATH to
    launch this process — that is always the file Windows has locked.
    """
    if not is_windows():
        return None
    return shutil.which("sync-db") or shutil.which("sync-db.exe")


def cmd_update(args: argparse.Namespace) -> int:
    uv = shutil.which("uv")
    if not uv:
        console.print("[red]ERRO[/] uv não encontrado.")
        console.print("Instale o uv e rode novamente: powershell -ExecutionPolicy Bypass -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
        return 1

    branch = getattr(args, "branch", "main") or "main"
    repo_url = getattr(args, "repo_url", PROJECT_REPO_URL) or PROJECT_REPO_URL
    target = f"git+{repo_url}@{branch}"
    renamed_from: str | None = None
    renamed_to: str | None = None
    if is_windows():
        exe_path = find_running_sync_db_exe()
        if exe_path and os.path.isfile(exe_path):
            old_path = exe_path + ".old"
            try:
                # Remove stale .old from a previous interrupted update so
                # os.rename doesn't fail (Windows won't overwrite via rename).
                if os.path.exists(old_path):
                    os.remove(old_path)
                os.rename(exe_path, old_path)
                renamed_from = exe_path
                renamed_to = old_path
            except OSError:
                pass  # não conseguiu renomear, segue sem o truque

    console.print(f"Atualizando sync-db a partir da {branch}...")
    proc = subprocess.run([uv, "tool", "install", "--reinstall", target], text=True, capture_output=True, check=False)
    if proc.stdout.strip():
        console.print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            console.print(proc.stderr.strip())
        # Restore the renamed exe so the tool isn't left broken.
        if renamed_from and renamed_to:
            try:
                if not os.path.exists(renamed_from):
                    os.rename(renamed_to, renamed_from)
            except OSError:
                pass
        console.print("[red]ERRO[/] Não foi possível atualizar o sync-db.")
        return proc.returncode or 1
    if proc.stderr.strip():
        console.print(proc.stderr.strip())
    if renamed_to:
        try:
            os.remove(renamed_to)
        except OSError:
            pass
    console.print("[green]Atualização concluída.[/]")
    console.print("Se o terminal antigo ainda mostrar a versão anterior, feche e abra o PowerShell/terminal novamente.")
    return 0


def cmd_doctor(paths: AppPaths) -> int:
    path = ensure_config(paths)
    config = load_config(paths)
    console.print(Panel.fit(f"[bold]Config[/]\n{path}", title="sync-db doctor", border_style="green"))

    managed = find_managed_client(paths, config["client"].get("vendor", "mariadb"))
    system = find_system_client(config["client"].get("vendor", "mariadb"))
    clients_table = Table(title=t("doctor.clients.title"))
    clients_table.add_column(t("status.item"))
    clients_table.add_column("Status")
    clients_table.add_column(t("status.details"))
    clients_table.add_row(t("status.managed_client"), "OK" if managed else "WARN", managed.describe() if managed else t("status.install_command"))
    clients_table.add_row(t("status.system_client"), "OK" if system else "WARN", system.describe() if system else t("status.not_found_path"))
    clients_table.add_row(t("status.python_engine"), "OK", t("status.available"))
    resolved = resolve_client(paths, config["client"].get("mode", "auto"), config["client"].get("preferred_source", "managed"), config["client"].get("vendor", "mariadb"))
    clients_table.add_row(t("status.recommended_engine"), resolved.kind, resolved.reason)
    console.print(clients_table)

    failed = False
    profiles = config.get("profiles", {})
    conn_table = Table(title=t("doctor.connections.title"))
    conn_table.add_column("Tag")
    conn_table.add_column(t("doctor.name"))
    conn_table.add_column("Host")
    conn_table.add_column("Database")
    conn_table.add_column("Status")
    conn_table.add_column(t("doctor.version_message"))
    if not profiles:
        console.print(f"[yellow]WARN[/] {t('doctor.no_databases')}")
    for tag, db_cfg in profiles.items():
        if not db_cfg.get("host") or not db_cfg.get("database") or not db_cfg.get("user"):
            conn_table.add_row(tag, db_cfg.get("label", ""), db_cfg.get("host", ""), db_cfg.get("database", ""), "WARN", t("status.incomplete_connection"))
            continue
        ok, msg = test_connection(db_cfg)
        conn_table.add_row(tag, db_cfg.get("label", ""), db_cfg.get("host", ""), db_cfg.get("database", ""), "OK" if ok else "ERRO", msg)
        failed = failed or not ok
    console.print(conn_table)
    return 1 if failed else 0


def collect_tables(args: argparse.Namespace, config: dict | None = None) -> list[str]:
    values: list[str] = []
    if getattr(args, "tables", None):
        values.extend(args.tables)
    if getattr(args, "file", None):
        return parse_tables(values) + [t for t in parse_tables_file(args.file) if t not in parse_tables(values)]
    return parse_tables(values)


def last_tables_path(paths: AppPaths, config: dict) -> Path:
    configured = config.get("sync", {}).get("last_tables_file") or "last_tables.txt"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = paths.config_dir / path
    return path


def save_last_tables(paths: AppPaths, config: dict, tables: list[str]) -> Path:
    path = last_tables_path(paths, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(tables) + "\n", encoding="utf-8")
    return path


def read_last_tables(paths: AppPaths, config: dict) -> list[str]:
    path = last_tables_path(paths, config)
    if not path.exists():
        return []
    return parse_tables_file(path)


def suggested_backup_name(table: str, suffix: str | None = None) -> str:
    suffix = suffix or datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{table.split('.')[-1]}_syncdb_backup_{suffix}"


def cleanup_temporary_backups(runtime_config: dict, backup_mode: str, results: list) -> None:
    if backup_mode != "temp":
        return
    destino = runtime_config.get("destino", {})
    for result in results:
        if result.ok and result.backup_table:
            try:
                drop_table(destino, result.backup_table)
                result.message = (result.message + " " if result.message else "") + "backup temporário removido"
                result.backup_table = None
            except Exception as exc:  # noqa: BLE001
                result.ok = False
                result.stage = "cleanup_backup"
                result.message = f"Sync concluiu, mas falhou ao remover backup temporário {result.backup_table}: {exc}"


def cmd_sync(paths: AppPaths, args: argparse.Namespace) -> int:
    config = load_config(paths)
    tables = read_last_tables(paths, config) if getattr(args, "last", False) else collect_tables(args, config)
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada. Use -t, -f ou --last.")
        return 2

    try:
        runtime_config = sync_runtime_config(config, getattr(args, "origin", None), getattr(args, "destination", None))
    except ValueError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        return 2
    backup_mode = getattr(args, "backup", None) or "none"
    runtime_config.setdefault("sync", {})["backup_before_replace"] = backup_mode in {"temp", "keep"}
    where_clause = normalize_where_clause(getattr(args, "where", None))
    insert_missing = bool(getattr(args, "insert_missing", False))
    dry_run = bool(getattr(args, "dry_run", False))
    advanced = bool(where_clause or insert_missing)
    console.print(f"Fluxo: [bold]{runtime_config['origem']['alias']}[/] → [bold]{runtime_config['destino']['alias']}[/]")
    if not dry_run:
        save_last_tables(paths, config, tables)

    if advanced:
        return cmd_sync_advanced(paths, runtime_config, tables, where_clause, insert_missing, backup_mode, yes=bool(getattr(args, "yes", False)), dry_run=dry_run)

    mode = args.mode or config.get("client", {}).get("mode", "auto")
    resolved = resolve_client(paths, mode, config["client"].get("preferred_source", "managed"), config["client"].get("vendor", "mariadb"))
    if resolved.kind == "missing":
        console.print(f"[red]ERRO[/] {resolved.reason}")
        console.print("Opções: sync-db client install | instalar cliente no sistema | --mode python")
        return 1
    console.print(f"Motor: [bold]{resolved.kind}[/] — {resolved.reason}")
    if dry_run:
        console.print("[yellow]DRY-RUN[/] Nenhuma alteração será feita no destino.")
        preview = Table(title="Prévia da sincronização")
        preview.add_column("Tabela")
        preview.add_column("Ação")
        preview.add_column("Motor")
        preview.add_column("Backup")
        for table_name in tables:
            preview.add_row(table_name, "substituir tabela inteira", resolved.kind, backup_mode)
        console.print(preview)
        write_sync_log(paths, runtime_config, tables, resolved.kind, [], sync_type="dry_run")
        return 0

    results = []
    progress_cm = sync_progress(len(tables)) if sys.stdin.isatty() else nullcontext(None)
    with progress_cm as progress:
        task_id = progress.add_task(t("menu.sync.title"), total=len(tables)) if progress else None
        for table in tables:
            console.print(f"\n[bold cyan]Sincronizando {table}[/]")
            if progress and task_id is not None:
                progress.update(task_id, description=f"Sincronizando {table}")
                if resolved.kind == "dump" and resolved.client:
                    result = run_dump_sync(runtime_config, table, resolved.client, paths)
                else:
                    result = run_python_sync(runtime_config, table)
                progress.advance(task_id)
            else:
                with console.status(f"Carregando tabela {table}...", spinner="dots"):
                    if resolved.kind == "dump" and resolved.client:
                        result = run_dump_sync(runtime_config, table, resolved.client, paths)
                    else:
                        result = run_python_sync(runtime_config, table)
            results.append(result)
            if result.ok:
                extra = f" backup={result.backup_table}" if result.backup_table else ""
                console.print(f"[green]OK[/] {table} ({result.engine}) rows={result.rows}{extra}")
            else:
                stage = f" etapa={result.stage}" if result.stage else ""
                console.print(f"[red]FALHOU[/] {table}{stage}: {result.message}")

    cleanup_temporary_backups(runtime_config, backup_mode, results)

    table = Table(title="Resumo")
    table.add_column("Tabela")
    table.add_column("Status")
    table.add_column("Engine")
    table.add_column("Etapa")
    table.add_column("Linhas")
    table.add_column("Backup")
    for result in results:
        table.add_row(result.table, "OK" if result.ok else "FALHOU", result.engine, result.stage or "", "" if result.rows is None else str(result.rows), result.backup_table or "")
    console.print(table)
    write_sync_log(paths, runtime_config, tables, resolved.kind, results)
    return 0 if all(r.ok for r in results) else 1


def print_sync_summary(results: list) -> None:
    table = Table(title="Resumo")
    table.add_column("Tabela")
    table.add_column("Status")
    table.add_column("Engine")
    table.add_column("Etapa")
    table.add_column("Linhas")
    table.add_column("Backup")
    for result in results:
        table.add_row(result.table, "OK" if result.ok else "FALHOU", result.engine, result.stage or "", "" if result.rows is None else str(result.rows), result.backup_table or "")
    console.print(table)


def cmd_sync_advanced(paths: AppPaths, runtime_config: dict, tables: list[str], where_clause: str, insert_missing: bool, backup_mode: str, *, yes: bool = False, dry_run: bool = False) -> int:
    sync_type = "where_insert_missing" if where_clause and insert_missing else "where_replace" if where_clause else "insert_missing"
    console.print(f"Motor: [bold]python/advanced[/] — sincronização avançada usa Python nesta versão.")
    if where_clause:
        console.print("[yellow]Atenção:[/] o mesmo WHERE será validado e aplicado em todas as tabelas selecionadas.")
    if insert_missing and len(tables) > 1:
        console.print("[yellow]Atenção:[/] as tabelas serão processadas na ordem informada; dependências/FKs não são ordenadas automaticamente.")

    preflight = preflight_advanced_sync(runtime_config, tables, where_clause, insert_missing)
    failures = [result for result in preflight if not result.ok]
    if failures:
        console.print("[red]ERRO[/] A condição/estrutura não é válida para todas as tabelas.")
        for failure in failures:
            console.print(f"[red]FALHOU[/] {failure.table} etapa={failure.stage}: {failure.message}")
        console.print("Nenhuma tabela foi sincronizada.")
        write_sync_log(paths, runtime_config, tables, "python/advanced", preflight, sync_type=sync_type, where_clause=where_clause)
        return 2

    preview = Table(title="Prévia da sincronização avançada")
    preview.add_column("Tabela")
    preview.add_column("PK")
    preview.add_column("Linhas na origem")
    if insert_missing:
        preview.add_column("Já existentes no destino")
        preview.add_column("Novas no destino")
    elif where_clause:
        preview.add_column("Afetadas no destino")
        preview.add_column("Inseridas após substituir")
    for result in preflight:
        row = [result.table, ", ".join(result.primary_key or []), "" if result.origin_matched_rows is None else str(result.origin_matched_rows)]
        if insert_missing:
            row.extend([
                "" if result.destination_matched_rows is None else str(result.destination_matched_rows),
                "" if result.planned_insert_rows is None else str(result.planned_insert_rows),
            ])
        elif where_clause:
            row.extend([
                "" if result.destination_matched_rows is None else str(result.destination_matched_rows),
                "" if result.planned_insert_rows is None else str(result.planned_insert_rows),
            ])
        preview.add_row(*row)
    console.print(preview)
    if dry_run:
        console.print("[yellow]DRY-RUN[/] Nenhuma alteração será feita no destino.")
        write_sync_log(paths, runtime_config, tables, "python/advanced", preflight, sync_type=f"dry_run_{sync_type}", where_clause=where_clause)
        return 0
    needs_risk_confirmation = len(tables) > 1 and bool(where_clause or insert_missing)
    if needs_risk_confirmation and not yes:
        if not sys.stdin.isatty():
            console.print("[red]ERRO[/] Sincronização avançada com várias tabelas exige confirmação. Use -y/--yes para executar sem prompt.")
            return 2
        if not confirm("Continuar com a sincronização avançada?"):
            console.print("Cancelado.")
            return 1

    results = []
    progress_cm = sync_progress(len(tables)) if sys.stdin.isatty() else nullcontext(None)
    with progress_cm as progress:
        task_id = progress.add_task(t("menu.sync.title"), total=len(tables)) if progress else None
        for table in tables:
            console.print(f"\n[bold cyan]Sincronizando {table}[/]")
            if progress and task_id is not None:
                progress.update(task_id, description=f"Sincronizando {table}")
                result = run_python_advanced_sync(runtime_config, table, where_clause=where_clause, insert_missing=insert_missing)
                progress.advance(task_id)
            else:
                with console.status(f"Sincronização avançada de {table}...", spinner="dots"):
                    result = run_python_advanced_sync(runtime_config, table, where_clause=where_clause, insert_missing=insert_missing)
            results.append(result)
            if result.ok:
                console.print(f"[green]OK[/] {table} ({result.sync_type}) inseridas={result.inserted_rows or 0} ignoradas={result.skipped_existing_rows or 0} removidas={result.deleted_rows or 0}")
            else:
                console.print(f"[red]FALHOU[/] {table} etapa={result.stage}: {result.message}")

    cleanup_temporary_backups(runtime_config, backup_mode, results)
    print_sync_summary(results)
    write_sync_log(paths, runtime_config, tables, "python/advanced", results, sync_type=sync_type, where_clause=where_clause)
    return 0 if all(result.ok for result in results) else 1


def cmd_backup(paths: AppPaths, args: argparse.Namespace) -> int:
    config = load_config(paths)
    tables = collect_tables(args, config)
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada. Use -t ou -f.")
        return 2
    tag = getattr(args, "destination", None) or config.get("defaults", {}).get("destination")
    if tag not in config.get("profiles", {}):
        console.print(f"[red]ERRO[/] Banco não encontrado: {tag}")
        return 2
    db_config = dict(config["profiles"][tag])
    db_config["alias"] = tag
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    console.print(f"Banco: [bold]{tag}[/]")
    for table in tables:
        suggested = suggested_backup_name(table, suffix)
        backup_name = suggested if getattr(args, "yes", False) else ask(f"Nome do backup para {table}", suggested)
        with console.status(f"Criando backup {backup_name}...", spinner="dots"):
            result = run_table_backup(db_config, table, backup_name)
        results.append(result)
        if result.ok:
            console.print(f"[green]OK[/] {table} → {result.backup_table}")
        else:
            console.print(f"[red]FALHOU[/] {table}: {result.message}")
    table_out = Table(title="Backups")
    table_out.add_column("Tabela")
    table_out.add_column("Status")
    table_out.add_column("Backup")
    for result in results:
        table_out.add_row(result.table, "OK" if result.ok else "FALHOU", result.backup_table or "")
    console.print(table_out)
    return 0 if all(result.ok for result in results) else 1


def cmd_schema(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.schema_command or "diff"
    try:
        action = normalize_schema_action(getattr(args, "plan_action", None) if sub == "plan" else sub)
    except ValueError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        return 2
    config = load_config(paths)
    tables = collect_tables(args, config)
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada. Use -t ou -f.")
        return 2
    try:
        origin, destination = resolve_profile_pair(config, getattr(args, "origin", None), getattr(args, "destination", None))
    except ValueError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        return 2

    if sub != "plan" and action in {SchemaAction.COPY, SchemaAction.UPDATE} and not getattr(args, "yes", False) and not getattr(args, "interactive", False) and not sys.stdin.isatty():
        console.print("[red]ERRO[/] schema copy/update em modo não interativo exige -y/--yes.")
        return 2
    if action == SchemaAction.RECREATE_TABLE and not getattr(args, "yes", False) and not sys.stdin.isatty():
        console.print("[red]ERRO[/] schema recreate-table em modo não interativo exige -y/--yes.")
        return 2

    sql_only = bool(getattr(args, "sql_only", False))
    if not sql_only and not getattr(args, "save", None):
        console.print(t("schema.model", origin=origin["alias"]))
        console.print(t("schema.target", destination=destination["alias"]))
        console.print(t("schema.tables", tables=", ".join(tables)))

    if action == SchemaAction.DIFF:
        results = []
        for table in tables:
            try:
                source_schema, target_schema = inspect_schema_pair(origin, destination, table)
                results.append((compare_schema(source_schema, target_schema), source_schema, target_schema))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]FALHOU[/] {table}: {exc}")
                return 1
        for diff, source_schema, target_schema in results:
            print_schema_diff(diff)
            if getattr(args, "verbose", False):
                print_schema_timings(origin["alias"], source_schema.timings, destination["alias"], target_schema.timings)
        return 0 if all(diff.source_exists and diff.target_exists for diff, _, _ in results) else 1

    if sub == "plan" and action in {SchemaAction.COPY, SchemaAction.UPDATE}:
        plans = []
        for table in tables:
            try:
                source_schema, target_schema = inspect_schema_pair(origin, destination, table)
                plans.append(build_schema_plan(compare_schema(source_schema, target_schema), action, source=source_schema, target=target_schema))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]FALHOU[/] {table}: {exc}")
                return 1
        save_path = getattr(args, "save", None)
        if save_path:
            output_path = Path(save_path).expanduser()
            if output_path.exists():
                console.print(f"[red]ERRO[/] Arquivo já existe: {output_path}. Escolha outro nome para não sobrescrever.")
                return 2
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                render_schema_plan_sql_file(plans, origin=origin["alias"], destination=destination["alias"], include_final_sql=bool(getattr(args, "sql", False)), show_item_sql=not bool(getattr(args, "no_sql", False)), sql_only=sql_only),
                encoding="utf-8",
            )
            console.print(f"[green]Plano salvo:[/] {output_path}")
            return 0
        if sql_only:
            print_schema_final_sql(plans, heading=False)
        else:
            for plan in plans:
                print_schema_plan(plan, show_sql=not bool(getattr(args, "no_sql", False)))
            if getattr(args, "sql", False):
                print_schema_final_sql(plans)
            console.print(f"[yellow]{t('no_changes')}[/]")
        return 0

    if action in {SchemaAction.COPY, SchemaAction.UPDATE}:
        plans = []
        for table in tables:
            try:
                source_schema, target_schema = inspect_schema_pair(origin, destination, table)
                plans.append(build_schema_plan(compare_schema(source_schema, target_schema), action, source=source_schema, target=target_schema))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]FALHOU[/] {table}: {exc}")
                return 1
        if sql_only:
            print_schema_final_sql(plans, heading=False)
        else:
            for plan in plans:
                print_schema_plan(plan, show_sql=not bool(getattr(args, "no_sql", False)))
            if getattr(args, "sql", False):
                print_schema_final_sql(plans)
        if not getattr(args, "yes", False):
            if getattr(args, "interactive", False):
                choice = read_text_or_back(t("prompt.apply_choice"))
                if choice is None or choice.strip().lower() not in {"a", "aplicar", "apply"}:
                    console.print(t("prompt.cancelled_no_changes"))
                    return 0
                typed = read_text_or_back(t("prompt.apply_plan"))
                if typed is None:
                    console.print(t("prompt.cancelled_no_changes"))
                    return 0
            else:
                typed = input(t("prompt.apply_plan")).strip()
            if typed.upper() != t("prompt.apply_word"):
                console.print(t("prompt.cancelled_no_changes"))
                return 1
        for plan in plans:
            report = execute_schema_plan(destination, plan)
            if report.ok:
                console.print(f"[green]OK[/] {plan.table}: {len(report.applied)} SQL aplicado(s).")
            else:
                console.print(f"[red]FALHOU[/] {plan.table}: após {len(report.applied)} SQL aplicado(s), falhou: {report.failed}")
                console.print(f"[red]ERRO[/] {report.error}")
                return 1
        return 0

    if action == SchemaAction.RECREATE_TABLE:
        keep_backup = bool(getattr(args, "keep_backup", False))
        if not getattr(args, "yes", False):
            keep_backup = input("Deseja manter tabela atual como backup? [s/N]").strip().lower() == "s"
            typed = input(t("prompt.apply_recreate")).strip()
            if typed.upper() != t("prompt.apply_word"):
                console.print(t("prompt.cancelled_no_changes"))
                return 1
        for table in tables:
            report = execute_recreate_table(origin, destination, table, keep_backup=keep_backup)
            if report.ok:
                backup_text = f" Backup mantido: {report.backup_table}." if report.backup_table else " Tabela anterior removida após a troca segura."
                console.print(f"[green]OK[/] {table}: recriada com a estrutura de {origin['alias']}.{backup_text}")
            else:
                console.print(f"[red]FALHOU[/] {table}: falhou em {report.failed}")
                console.print(f"[red]ERRO[/] {report.error}")
                if report.backup_table:
                    console.print(f"[yellow]A tabela anterior foi preservada como backup: {report.backup_table}.[/]")
                return 1
        return 0

    console.print(f"Ação de estrutura: {describe_schema_action(action)}")
    console.print(f"[yellow]schema {action.value}[/] ainda não aplica alterações. Rode `sync-db schema plan {action.value}` para revisar o plano.")
    return 0


def print_schema_diff(diff: SchemaDiff) -> None:
    console.print(f"\n[bold cyan]Tabela: {diff.table}[/]")
    if not diff.source_exists:
        console.print(f"[red]{t('schema.no_table', side=t('schema.origin'))}[/]")
        return
    if not diff.target_exists:
        console.print(f"[yellow]{t('schema.no_table', side=t('schema.destination'))}[/]")
        return
    if diff.is_equal:
        console.print(f"[green]{t('schema.identical')}[/]")
        return
    rows = (
        (t("schema.diff.missing_columns"), diff.missing_columns),
        (t("schema.diff.changed_columns"), diff.changed_columns),
        (t("schema.diff.reordered_columns"), diff.reordered_columns),
        (t("schema.diff.extra_columns"), diff.extra_columns),
        (t("schema.diff.missing_indexes"), diff.missing_indexes),
        (t("schema.diff.changed_indexes"), diff.changed_indexes),
        (t("schema.diff.extra_indexes"), diff.extra_indexes),
        (t("schema.diff.missing_foreign_keys"), diff.missing_foreign_keys),
        (t("schema.diff.changed_foreign_keys"), diff.changed_foreign_keys),
        (t("schema.diff.extra_foreign_keys"), diff.extra_foreign_keys),
        (t("schema.diff.changed_table_options"), diff.changed_table_options),
    )
    for label, names in rows:
        if names:
            console.print(f"[yellow]{label}:[/] {', '.join(names)}")
    if diff.column_changes:
        preview = diff.column_changes[:12]
        details = ", ".join(f"{name} ({'/'.join(reasons)})" for name, reasons in preview)
        suffix = f"; +{len(diff.column_changes) - len(preview)}" if len(diff.column_changes) > len(preview) else ""
        console.print(f"[dim]Motivos das diferenças de coluna: {details}{suffix}[/]")


def print_schema_timings(source_label: str, source_timings: tuple[tuple[str, float], ...], target_label: str, target_timings: tuple[tuple[str, float], ...]) -> None:
    def text(label: str, timings: tuple[tuple[str, float], ...]) -> str:
        return f"{label}: " + ", ".join(f"{name}={seconds:.2f}s" for name, seconds in timings)

    console.print(f"[dim]Tempos de leitura — {text(source_label, source_timings)} | {text(target_label, target_timings)}[/]")


def render_schema_plan_sql_file(plans: list[SchemaPlan], *, origin: str, destination: str, include_final_sql: bool = False, show_item_sql: bool = True, sql_only: bool = False) -> str:
    statements = [statement for plan in plans for statement in _execution_statements(plan)]
    if sql_only:
        return "\n".join(statements) + ("\n" if statements else "")

    symbols = {"add": "+", "modify": "~", "move": "↔", "drop": "-", "replace": "~", "preserve": "!"}
    labels = {"column": t("schema.column"), "index": t("schema.index"), "foreign_key": t("schema.foreign_key"), "table_option": t("schema.table_option")}
    sections = ((t("schema.add"), {"add"}), (t("schema.modify"), {"modify", "replace"}), (t("schema.move"), {"move"}), (t("schema.drop"), {"drop"}), (t("schema.preserve"), {"preserve"}))
    categories = (("column", t("schema.columns")), ("index", t("schema.indexes")), ("foreign_key", t("schema.foreign_keys")), ("table_option", t("schema.table_options")))
    lines = ["-- sync-db schema plan", f"-- Origem: {origin}", f"-- Destino: {destination}"]
    for plan in plans:
        lines.extend(("", f"-- {t('schema.plan', table=plan.table, action=plan.action.value)}"))
        for title, actions in sections:
            selected = [operation for operation in plan.operations if operation.action in actions]
            if not selected:
                continue
            lines.append(f"--     {title} ({len(selected)})")
            for category, category_title in categories:
                grouped = [operation for operation in selected if operation.category == category]
                if not grouped:
                    continue
                lines.append(f"--         {category_title} ({len(grouped)})")
                for operation in grouped:
                    lines.append(f"--             {symbols[operation.action]} {labels[operation.category]} {operation.name}")
                    lines.extend(f"--               ┗> {detail}" for detail in operation.details)
                    if operation.sql and show_item_sql:
                        for statement in _operation_statements(operation):
                            lines.append(f"--               SQL: {statement}" if include_final_sql else f"              {statement}")
                            lines.append("")
    if include_final_sql or not show_item_sql:
        lines.append(f"\n-- {t('schema.final_sql')}")
        lines.extend(statements)
    return "\n".join(lines) + "\n"


def print_schema_final_sql(plans: list[SchemaPlan], *, heading: bool = True) -> None:
    statements = [statement for plan in plans for statement in _execution_statements(plan)]
    if not statements:
        return
    if heading:
        console.print(f"\n[bold cyan]{t('schema.final_sql')}[/]")
    for statement in statements:
        console.print(statement)


def print_schema_plan(plan: SchemaPlan, *, show_sql: bool = False) -> None:
    console.print(f"\n[bold cyan]{t('schema.plan', table=plan.table, action=plan.action.value)}[/]")
    if not plan.operations:
        console.print(f"[green]{t('schema.no_changes')}[/]")
        return
    symbols = {"add": "+", "modify": "~", "move": "↔", "drop": "-", "replace": "~", "preserve": "!"}
    styles = {"add": "green", "modify": "yellow", "move": "blue", "drop": "red", "replace": "yellow", "preserve": "cyan"}
    labels = {"column": t("schema.column"), "index": t("schema.index"), "foreign_key": t("schema.foreign_key"), "table_option": t("schema.table_option")}
    sections = ((t("schema.add"), {"add"}), (t("schema.modify"), {"modify", "replace"}), (t("schema.move"), {"move"}), (t("schema.drop"), {"drop"}), (t("schema.preserve"), {"preserve"}))
    category_titles = {"column": t("schema.columns"), "index": t("schema.indexes"), "foreign_key": t("schema.foreign_keys"), "table_option": t("schema.table_options")}
    for title, actions in sections:
        selected = [operation for operation in plan.operations if operation.action in actions]
        if not selected:
            continue
        console.print(f"\n    [bold]{title} ({len(selected)})[/]")
        printed_category = False
        for category in ("column", "index", "foreign_key", "table_option"):
            grouped = [operation for operation in selected if operation.category == category]
            if not grouped:
                continue
            if printed_category:
                console.print()
            printed_category = True
            console.print(f"        [bold cyan]{category_titles[category]} ({len(grouped)})[/]")
            for operation_index, operation in enumerate(grouped):
                if operation_index:
                    console.print()
                console.print(f"            [{styles[operation.action]}]{symbols[operation.action]}[/] [bold]{labels[operation.category]}[/] {operation.name}")
                for detail in operation.details:
                    console.print(f"              [dim]┗> {detail}[/]")
                if show_sql and operation.sql:
                    console.print("              [dim]SQL:[/]")
                    for sql_line in operation.sql.splitlines():
                        console.print(f"              [dim]{sql_line}[/]")
    if plan.has_destructive_operations:
        console.print(f"[yellow]{t('schema.destructive')}[/]")


def write_sync_log(paths: AppPaths, runtime_config: dict, tables: list[str], engine: str, results: list, *, sync_type: str = "full_replace", where_clause: str = "") -> Path:
    paths.ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origin": runtime_config.get("origem", {}).get("alias"),
        "destination": runtime_config.get("destino", {}).get("alias"),
        "origin_host": runtime_config.get("origem", {}).get("host"),
        "destination_host": runtime_config.get("destino", {}).get("host"),
        "tables": tables,
        "engine": engine,
        "sync_type": sync_type,
        "where": where_clause,
        "status": "ok" if all(result.ok for result in results) else "failed",
        "results": [
            {
                "table": result.table,
                "ok": result.ok,
                "engine": result.engine,
                "rows": result.rows,
                "message": result.message,
                "stage": result.stage,
                "backup_table": result.backup_table,
                "sync_type": getattr(result, "sync_type", "full_replace"),
                "primary_key": getattr(result, "primary_key", None),
                "origin_matched_rows": getattr(result, "origin_matched_rows", None),
                "deleted_rows": getattr(result, "deleted_rows", None),
                "inserted_rows": getattr(result, "inserted_rows", None),
                "skipped_existing_rows": getattr(result, "skipped_existing_rows", None),
            }
            for result in results
        ],
    }
    with paths.log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return paths.log_file


def cmd_tables(args: argparse.Namespace) -> int:
    tables = collect_tables(args)
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada. Use `sync-db tables -t tabela` ou `sync-db tables -f tabelas.csv`.")
        return 2
    for i, table in enumerate(tables, 1):
        console.print(f"{i}. {table}")
    return 0


def choose_editor(os_name: str | None = None) -> str:
    os_name = os_name or os.name
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if os_name == "nt":
        # Shells are common EDITOR values in PowerShell profiles and cause `config edit`
        # to open a nested shell instead of the JSON file.
        bad_shells = {"pwsh", "pwsh.exe", "powershell", "powershell.exe", "cmd", "cmd.exe"}
        if editor and Path(editor).name.lower() not in bad_shells:
            return editor
        return "notepad"
    return editor or "nano"


def open_editor(editor: str, path: Path, os_name: str | None = None) -> int:
    if (os_name or os.name) == "nt":
        subprocess.Popen([editor, str(path)])
        console.print(f"Editor aberto: {path}")
        return 0
    return subprocess.call([editor, str(path)])


def cmd_config(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.config_command or "path"
    if sub == "path":
        console.print(str(ensure_config(paths)))
    elif sub == "show":
        console.print_json(json.dumps(redact_config(load_config(paths)), ensure_ascii=False))
    elif sub == "edit":
        path = ensure_config(paths)
        editor = choose_editor()
        return open_editor(editor, path)
    elif sub == "remove":
        path = paths.config_file
        if path.exists() and confirm(f"Remover config {path}?"):
            path.unlink()
            console.print("[green]Config removido.[/]")
    return 0


def cmd_db(paths: AppPaths, args: argparse.Namespace) -> int:
    config = load_config(paths)
    sub = args.db_command or "list"
    if sub == "list":
        return cmd_db_list(config)
    if sub == "add":
        return cmd_db_add(paths, config, getattr(args, "tag", None))
    if sub == "edit":
        return cmd_db_add(paths, config, args.tag, editing=True)
    if sub == "remove":
        tag = args.tag
        if tag not in config.get("profiles", {}):
            console.print(f"[red]ERRO[/] Banco não encontrado: {tag}")
            return 2
        if confirm(f"Remover banco {tag}?"):
            config["profiles"].pop(tag)
            for key in ("origin", "destination"):
                if config.get("defaults", {}).get(key) == tag:
                    config["defaults"][key] = ""
            save_config(config, paths)
            console.print(f"[green]Banco removido:[/] {tag}")
        return 0
    if sub == "test":
        tag = args.tag or config.get("defaults", {}).get("origin")
        if tag not in config.get("profiles", {}):
            console.print(f"[red]ERRO[/] Banco não encontrado: {tag}")
            return 2
        ok, msg = test_connection(config["profiles"][tag])
        if ok:
            console.print(f"[green]OK[/] {tag}: MySQL/MariaDB {msg}")
            return 0
        console.print(f"[red]ERRO[/] {tag}: {msg}")
        return 1
    if sub == "set-defaults":
        try:
            resolve_profile_pair(config, args.origin, args.destination)
        except ValueError as exc:
            console.print(f"[red]ERRO[/] {exc}")
            return 2
        config.setdefault("defaults", {})["origin"] = args.origin
        config.setdefault("defaults", {})["destination"] = args.destination
        save_config(config, paths)
        console.print(f"Origem padrão: {args.origin}")
        console.print(f"Destino padrão: {args.destination}")
        return 0
    return cmd_db_list(config)


def cmd_db_list(config: dict, *, show_numbers: bool = False) -> int:
    table = Table(title="Bancos cadastrados")
    if show_numbers:
        table.add_column("#")
    table.add_column("Tag")
    table.add_column("Label")
    table.add_column("Host")
    table.add_column("Database")
    table.add_column("Uso")
    defaults = config.get("defaults", {})
    for index, (tag, profile) in enumerate(config.get("profiles", {}).items(), 1):
        marks = []
        if defaults.get("origin") == tag:
            marks.append("origem padrão")
        if defaults.get("destination") == tag:
            marks.append("destino padrão")
        if not profile.get("allow_as_destination", True):
            marks.append("source_only")
        row = [tag, profile.get("label", ""), profile.get("host", ""), profile.get("database", ""), ", ".join(marks)]
        if show_numbers:
            row.insert(0, str(index))
        table.add_row(*row)
    console.print(table)
    return 0


def cmd_db_add(paths: AppPaths, config: dict, tag: str | None, *, editing: bool = False) -> int:
    profiles = config.setdefault("profiles", {})
    if not tag:
        tag = profile_tag(input("Apelido curto do banco (ex: prod, local, homolog): "))
    tag = profile_tag(tag)
    current = profiles.get(tag, {}) if editing else {}
    if editing and tag not in profiles:
        console.print(f"[red]ERRO[/] Banco não encontrado: {tag}")
        return 2
    if not editing and tag in profiles:
        console.print(f"[red]ERRO[/] Banco {tag} já existe. Use `sync-db db edit {tag}` para alterar.")
        return 2
    profile = {
        "label": ask("Rótulo amigável", current.get("label", tag)),
        "host": ask("Host", current.get("host", "")),
        "port": int(ask("Porta", str(current.get("port", 3306))) or 3306),
        "user": ask("Usuário", current.get("user", "")),
        "password": ask("Senha", current.get("password", "")),
        "database": ask("Banco/database", current.get("database", "")),
        "charset": ask("Charset", current.get("charset", "latin1"), hint="latin1, utf8"),
        "allow_as_origin": confirm_default("Pode ser origem?", bool(current.get("allow_as_origin", True))),
        "allow_as_destination": confirm_default("Pode ser destino?", bool(current.get("allow_as_destination", True))),
    }
    profiles[tag] = profile
    save_config(config, paths)
    console.print(f"[green]Banco salvo:[/] {tag}")
    if confirm("Testar conexão agora?"):
        ok, msg = test_connection(profile)
        console.print(("[green]OK[/] " if ok else "[red]ERRO[/] ") + msg)
        return 0 if ok else 1
    return 0


def ask(label: str, default: str = "", *, hint: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    hint_suffix = f" ({hint})" if hint else ""
    value = input(f"{label}{suffix}{hint_suffix}: ").strip()
    return value if value else default


def confirm_default(question: str, default: bool, *, default_label: str = "") -> bool:
    suffix = "S/n" if default else "s/N"
    label = f" {default_label}" if default_label else ""
    answer = input(f"{question} [{suffix}]{label} ").strip().lower()
    if not answer:
        return default
    return answer in {"s", "sim", "y", "yes"}


def cmd_client(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.client_command or "status"
    if sub == "status":
        managed = find_managed_client(paths)
        system = find_system_client()
        table = Table(title=t("client.title"))
        table.add_column(t("status.item"))
        table.add_column("Status")
        table.add_column(t("status.details"))
        table.add_row(t("client.managed_folder"), "OK", str(paths.managed_client_dir))
        table.add_row(t("status.managed_client"), "OK" if managed else "WARN", managed.describe() if managed else t("status.not_installed"))
        table.add_row(t("status.system_client"), "OK" if system else "WARN", system.describe() if system else t("status.not_found"))
        table.add_row(t("status.python_engine"), "OK", t("status.available"))
        console.print(table)
    elif sub == "path":
        console.print(str(paths.managed_client_dir))
    elif sub in {"install", "update"}:
        return cmd_client_install(paths, args)
    elif sub == "remove":
        if paths.managed_client_dir.exists() and confirm(f"Remover {paths.managed_client_dir}?"):
            shutil.rmtree(paths.managed_client_dir)
            console.print("[green]Cliente gerenciado removido.[/]")
        else:
            console.print("Nada removido.")
    return 0


def cmd_client_install(paths: AppPaths, args: argparse.Namespace) -> int:
    console.print("Este comando instala o cliente MariaDB gerenciado")
    try:
        if args.archive_url:
            target_desc = args.archive_url
            sha_desc = args.sha256 or "não informado"
        else:
            package = resolve_default_package()
            target_desc = f"{package.file_name} ({package.os_name}/{package.cpu})"
            sha_desc = package.sha256
        console.print(f"Pacote: {target_desc}")
        console.print(f"Destino: {paths.managed_client_dir / 'mariadb' / 'current'}")
        console.print(f"SHA256: {sha_desc}")
        if not args.yes and not confirm("Continuar com a instalação do cliente MariaDB gerenciado?"):
            console.print("Cancelado.")
            return 1
        with console.status("Baixando e instalando cliente MariaDB gerenciado...", spinner="dots"):
            client = install_managed_client(paths, archive_url=args.archive_url, sha256=args.sha256)
        console.print(f"[green]Cliente gerenciado instalado:[/] {client.describe()}")
        return 0
    except ManagedClientError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]ERRO[/] Falha ao instalar cliente gerenciado: {exc}")
        return 1


def cmd_logs(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.logs_command or "path"
    if sub == "path":
        console.print(str(paths.log_dir))
    elif sub == "tail":
        if not paths.log_file.exists():
            console.print(f"Nenhum log encontrado ainda em {paths.log_file}")
            return 0
        lines = paths.log_file.read_text(encoding="utf-8").splitlines()
        for line in lines[-max(1, int(getattr(args, "lines", 40))):]:
            console.print(line)
    elif sub == "open":
        paths.log_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            subprocess.Popen(["explorer", str(paths.log_dir)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(paths.log_dir)])
        else:
            subprocess.Popen(["xdg-open", str(paths.log_dir)])
        console.print(str(paths.log_dir))
    elif sub == "clear":
        if paths.log_dir.exists() and confirm(f"Limpar logs em {paths.log_dir}?"):
            shutil.rmtree(paths.log_dir)
            paths.log_dir.mkdir(parents=True, exist_ok=True)
            console.print("[green]Logs limpos.[/]")
    return 0


def cmd_uninstall(paths: AppPaths, args: argparse.Namespace) -> int:
    console.print("Para desinstalar o comando instalado via uv/pipx, rode um dos comandos abaixo conforme seu instalador:")
    console.print("  uv tool uninstall database-table-cloning-tool")
    console.print("  pipx uninstall database-table-cloning-tool")
    if args.all:
        for path in (paths.config_dir, paths.data_dir, paths.state_dir, paths.cache_dir):
            console.print(f"Remover dados: {path}")
    else:
        console.print("Por padrão, mantenha o config para uma reinstalação futura.")
    return 0


def resolve_profile_input(config: dict, value: str, default: str = "") -> str:
    value = (value or "").strip()
    if not value:
        return default
    tags = list(config.get("profiles", {}).keys())
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(tags):
            return tags[index]
    return value


def ask_profile(config: dict, label: str, default: str = "") -> str:
    return resolve_profile_input(config, ask(label, default), default)


def profile_options(config: dict, *, include_back: bool = True) -> list[MenuOption]:
    options = [
        MenuOption(f"{tag} ({profile.get('label', '')})", tag, f"{profile.get('host', '')}/{profile.get('database', '')}")
        for tag, profile in config.get("profiles", {}).items()
    ]
    if include_back:
        options.append(MenuOption(t("menu.back"), "back"))
    return options


def choose_profile(config: dict, title: str, default: str = "", *, footer: str = "") -> str:
    options = profile_options(config)
    if len(options) <= 1:
        return ask_profile(config, title, default)
    tags = list(config.get("profiles", {}).keys())
    default_index = tags.index(default) if default in tags else 0
    selected = select_option(title, options, default_index=default_index, console=console, footer=footer)
    return selected


def pause_after_action() -> None:
    if sys.stdin.isatty():
        input(t("prompt.press_enter"))


def run_interactive_menu(paths: AppPaths) -> int:
    ensure_config(paths)
    last_status = 0
    while True:
        choice = select_option(
            t("menu.main"),
            [
                MenuOption(t("menu.sync"), "sync"),
                MenuOption(t("menu.advanced_sync"), "advanced_sync"),
                MenuOption(t("menu.schema"), "schema"),
                MenuOption(t("menu.backup"), "backup"),
                MenuOption(t("menu.databases"), "db"),
                MenuOption(t("menu.logs"), "logs"),
                MenuOption(t("menu.more"), "more"),
                MenuOption(t("menu.exit"), "exit"),
            ],
            console=console,
            compact=True,
        )
        if choice in {"exit", "back"}:
            print_exit_banner()
            return last_status
        if choice == "sync":
            status = interactive_sync(paths)
            if not is_menu_back(status):
                last_status = status
                pause_after_action()
        elif choice == "advanced_sync":
            status = interactive_advanced_sync(paths)
            if not is_menu_back(status):
                last_status = status
                pause_after_action()
        elif choice == "schema":
            status = interactive_schema(paths)
            if not is_menu_back(status):
                last_status = status
                pause_after_action()
        elif choice == "backup":
            status = interactive_backup(paths)
            if not is_menu_back(status):
                last_status = status
                pause_after_action()
        elif choice == "db":
            last_status = interactive_db(paths)
        elif choice == "logs":
            last_status = interactive_logs(paths)
        elif choice == "more":
            last_status = interactive_more(paths)
        if not sys.stdin.isatty():
            return last_status


def interactive_more(paths: AppPaths) -> int:
    while True:
        choice = select_option(
            t("menu.more.title"),
            [
                MenuOption(t("menu.defaults"), "defaults"),
                MenuOption(t("menu.doctor"), "doctor"),
                MenuOption(t("menu.update"), "update"),
                MenuOption(t("menu.client"), "client"),
                MenuOption(t("menu.language"), "language"),
                MenuOption(t("menu.uninstall"), "uninstall"),
                MenuOption(t("menu.back"), "back"),
            ],
            console=console,
        )
        if choice == "back":
            return 0
        if choice == "defaults":
            status = interactive_defaults(paths)
        elif choice == "doctor":
            status = cmd_doctor(paths)
            pause_after_action()
        elif choice == "update":
            status = cmd_update(argparse.Namespace(branch="main", repo_url=PROJECT_REPO_URL))
            pause_after_action()
        elif choice == "client":
            status = interactive_client(paths)
        elif choice == "language":
            status = interactive_language(paths)
        elif choice == "uninstall":
            status = cmd_uninstall(paths, argparse.Namespace(all=False, keep_config=True))
            pause_after_action()
        else:
            status = 0
        if not sys.stdin.isatty():
            return status


def interactive_language(paths: AppPaths) -> int:
    config = load_config(paths)
    selected = select_option(
        t("menu.language.title"),
        [
            MenuOption(t("language.pt"), "pt-BR"),
            MenuOption(t("language.en"), "en"),
            MenuOption(t("menu.back"), "back"),
        ],
        default_index=0 if get_language() == "pt-BR" else 1,
        console=console,
    )
    if selected != "back":
        set_config_language(paths, config, selected)
    return 0


def format_sync_context(*, origin: str = "", destination: str = "", tables: list[str] | None = None, mode: str = "", step: str = "") -> str:
    lines: list[str] = []
    if origin:
        lines.append(t("menu.context.origin", origin=origin))
    if destination:
        lines.append(t("menu.context.destination", destination=destination))
    if tables:
        lines.append(t("menu.context.tables", tables=", ".join(tables)))
    if mode:
        lines.append(t("menu.context.mode", mode=mode))
    step_text = {
        "origin": t("menu.step.origin"),
        "destination": t("menu.step.destination"),
        "tables": t("menu.step.tables"),
        "mode": t("menu.step.mode"),
    }.get(step, "")
    if step_text:
        lines.append(step_text)
    return "\n".join(lines)


def read_tables_input(prompt: str | None = None) -> list[str] | None:
    value = read_text_or_back(prompt or t("menu.table_prompt"))
    if value is None:
        return None
    return parse_tables([value])


def interactive_backup(paths: AppPaths) -> int:
    config = load_config(paths)
    destination = choose_profile(config, t("menu.backup.title"), config.get("defaults", {}).get("destination", ""), footer=t("menu.backup.choose_destination"))
    if destination == "back":
        return MENU_BACK
    console.print(Panel(t("menu.backup.context", destination=destination), title=t("menu.backup.title"), border_style="cyan"))
    tables = read_tables_input()
    if tables is None:
        return MENU_BACK
    if not tables:
        console.print(f"[red]{t('error')}[/] {t('menu.no_table')}")
        return 2
    console.print(t("menu.backup.names"))
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    selected_names = []
    for table in tables:
        selected_names.append(ask(t("menu.backup.name", table=table), suggested_backup_name(table, suffix)))
    args = argparse.Namespace(tables=tables, file=None, destination=destination, yes=True)
    original = suggested_backup_name
    names_iter = iter(selected_names)
    try:
        globals()["suggested_backup_name"] = lambda table, suffix=None: next(names_iter)
        return cmd_backup(paths, args)
    finally:
        globals()["suggested_backup_name"] = original


def _manual_schema_operation_options(plan: SchemaPlan, selected: set[int]) -> list[MenuOption]:
    symbols = {"add": "+", "modify": "~", "move": "↔", "drop": "-", "replace": "~"}
    labels = {"column": t("schema.column"), "index": t("schema.index"), "foreign_key": t("schema.foreign_key"), "table_option": t("schema.table_option")}
    options: list[MenuOption] = []
    for index, operation in enumerate(plan.operations):
        if operation.action == "preserve" or not operation.sql:
            continue
        mark = "[x]" if index in selected else "[ ]"
        group = f"{operation.action.upper()} — {labels.get(operation.category, operation.category).upper()}"
        details = "; ".join(operation.details) or group
        options.append(MenuOption(f"{mark} {symbols.get(operation.action, '?')} {labels.get(operation.category, operation.category)} {operation.name}", f"toggle:{index}", f"{group}. {details}"))
    options.extend((
        MenuOption(t("menu.manual.review"), "review"),
        MenuOption(t("menu.back"), "back"),
    ))
    return options


def interactive_manual_schema_selection(config: dict, origin_tag: str, destination_tag: str, tables: list[str]) -> int:
    """Inspect a fresh copy plan, then execute only explicitly selected operations."""
    action = SchemaAction.COPY
    origin = dict(config["profiles"][origin_tag])
    origin["alias"] = origin_tag
    destination = dict(config["profiles"][destination_tag])
    destination["alias"] = destination_tag
    plans: list[SchemaPlan] = []
    for table in tables:
        try:
            source_schema, target_schema = inspect_schema_pair(origin, destination, table)
            plans.append(build_schema_plan(compare_schema(source_schema, target_schema), action, source=source_schema, target=target_schema))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]FALHOU[/] {table}: {exc}")
            return 1

    selected_by_table: dict[str, set[int]] = {plan.table: set() for plan in plans}
    for plan in plans:
        selected = selected_by_table[plan.table]
        cursor_index = 0
        while True:
            options = _manual_schema_operation_options(plan, selected)
            choice = select_option(
                t("menu.manual.title") + f" — {plan.table}",
                options,
                default_index=cursor_index,
                console=console,
                footer=t("menu.manual.footer"),
            )
            if choice == "back":
                return MENU_BACK
            if choice == "review":
                break
            if isinstance(choice, str) and choice.startswith("toggle:"):
                index = int(choice.removeprefix("toggle:"))
                cursor_index = next((position for position, option in enumerate(options) if option.value == choice), cursor_index)
                if index in selected:
                    selected.remove(index)
                else:
                    selected.add(index)

    selected_plans = [
        SchemaPlan(plan.table, plan.action, tuple(operation for index, operation in enumerate(plan.operations) if index in selected_by_table[plan.table]))
        for plan in plans
    ]
    if not any(plan.operations for plan in selected_plans):
        console.print(f"[yellow]{t('menu.manual.none')}[/]")
        return 0
    console.print(f"\n[bold cyan]{t('menu.manual.review_title')}[/]")
    for plan in selected_plans:
        if plan.operations:
            print_schema_plan(plan, show_sql=True)
    typed = input(t("prompt.apply_selected")).strip()
    if typed.upper() != "APLICAR":
        console.print("Cancelado. Nenhuma alteração foi feita.")
        return 1
    for plan in selected_plans:
        if not plan.operations:
            continue
        report = execute_schema_plan(destination, plan)
        if not report.ok:
            console.print(f"[red]FALHOU[/] {plan.table}: após {len(report.applied)} SQL aplicado(s), falhou: {report.failed}")
            console.print(f"[red]ERRO[/] {report.error}")
            return 1
        console.print(f"[green]OK[/] {plan.table}: {len(report.applied)} SQL aplicado(s).")
    return 0


def interactive_schema(paths: AppPaths) -> int:
    config = load_config(paths)
    origin = choose_profile(config, t("menu.schema.origin"), config.get("defaults", {}).get("origin", ""))
    if origin == "back":
        return MENU_BACK
    destination = choose_profile(config, t("menu.schema.destination"), config.get("defaults", {}).get("destination", ""))
    if destination == "back":
        return MENU_BACK

    while True:
        console.print(Panel(
            t("menu.schema.model", origin=origin, destination=destination),
            title=t("menu.schema"),
            border_style="cyan",
        ))
        tables = read_tables_input()
        if tables is None:
            return MENU_BACK
        if not tables:
            console.print(f"[red]{t('error')}[/] {t('menu.no_table')}")
            return 2

        while True:
            choice = select_option(
                t("menu.schema"),
                [
                    MenuOption(t("menu.schema.diff"), "diff"),
                    MenuOption(t("menu.schema.copy"), "copy", t("menu.schema.copy_description")),
                    MenuOption(t("menu.schema.update"), "update", t("menu.schema.update_description")),
                    MenuOption(t("menu.schema.manual"), "manual", t("menu.schema.manual_description")),
                    MenuOption(t("menu.schema.recreate"), "recreate-table", t("menu.schema.recreate_description")),
                    MenuOption(t("menu.schema.main"), "main_menu"),
                ],
                console=console,
                footer=t("menu.schema.reselect"),
                hotkeys={"t": "reselect_tables"},
            )
            if choice in {"back", "reselect_tables"}:
                break
            if choice == "main_menu":
                return MENU_BACK
            if choice == "diff":
                status = cmd_schema(paths, argparse.Namespace(schema_command="diff", tables=tables, file=None, origin=origin, destination=destination, verbose=False))
            elif choice in {"copy", "update"}:
                status = cmd_schema(paths, argparse.Namespace(schema_command=choice, tables=tables, file=None, origin=origin, destination=destination, yes=False, interactive=True))
            elif choice == "manual":
                status = interactive_manual_schema_selection(config, origin, destination, tables)
            elif choice == "recreate-table":
                console.print(f"[yellow]{t('menu.schema.warning')}[/]")
                status = cmd_schema(paths, argparse.Namespace(schema_command="recreate-table", tables=tables, file=None, origin=origin, destination=destination, yes=False))
            else:
                continue

            if not sys.stdin.isatty():
                return status
            pause_after_action()


def profile_summary(config: dict, tag: str) -> str:
    profile = config.get("profiles", {}).get(tag, {})
    if not tag:
        return t("advanced.not_selected")
    return f"{tag} ({profile.get('host', '')}/{profile.get('database', '')})"


def advanced_rows_text(insert_missing: bool, where_clause: str = "") -> str:
    if insert_missing:
        return t("advanced.rows.missing")
    if where_clause:
        return t("advanced.rows.where")
    return t("advanced.rows.all")


def advanced_backup_text(backup_mode: str) -> str:
    if backup_mode == "keep":
        return "sim - mantém o backup no banco após sincronizar com sucesso"
    if backup_mode == "temp":
        return "sim - backup temporário, remove ao concluir com sucesso"
    return "não"


def advanced_backup_options() -> list[MenuOption]:
    return [
        MenuOption(t("advanced.none"), "none", t("advanced.backup.none")),
        MenuOption(t("advanced.backup.temp"), "temp", t("advanced.backup.temp_description")),
        MenuOption(t("advanced.backup.keep"), "keep", t("advanced.backup.keep_description")),
        MenuOption(t("menu.back"), "back"),
    ]


def advanced_mode_options(where_clause: str, insert_missing: bool) -> list[MenuOption]:
    if where_clause or insert_missing:
        return [MenuOption("python", "python", t("advanced.mode.required")), MenuOption(t("menu.back"), "back")]
    return [
        MenuOption("auto", "auto", t("advanced.mode.recommended")),
        MenuOption("managed-dump", "managed-dump", t("advanced.mode.managed")),
        MenuOption("system-dump", "system-dump", t("advanced.mode.system")),
        MenuOption("python", "python", t("advanced.mode.python")),
        MenuOption(t("menu.back"), "back"),
    ]


def advanced_menu_options(config: dict, origin: str, destination: str, tables: list[str], where_clause: str, insert_missing: bool, mode: str, backup_mode: str = "none") -> list[MenuOption]:
    where_text = f"WHERE {where_clause}" if where_clause else t("advanced.none")
    return [
        MenuOption(t("advanced.source"), "origin", profile_summary(config, origin)),
        MenuOption(t("advanced.destination"), "destination", profile_summary(config, destination)),
        MenuOption(t("advanced.tables"), "tables", ", ".join(tables) if tables else t("advanced.not_selected")),
        MenuOption(t("advanced.where"), "where", where_text),
        MenuOption(t("advanced.rows"), "rows", advanced_rows_text(insert_missing, where_clause)),
        MenuOption(t("advanced.engine"), "mode", mode),
        MenuOption(t("advanced.run"), "run"),
        MenuOption(t("menu.back"), "back"),
    ]


def format_advanced_sync_state(config: dict, origin: str, destination: str, tables: list[str], where_clause: str, insert_missing: bool, mode: str, backup_mode: str = "none") -> str:
    where_text = f"WHERE {where_clause}" if where_clause else t("advanced.none")
    rows_text = advanced_rows_text(insert_missing, where_clause)
    return "\n".join([
        t("advanced.source"),
        f"    ┗> {profile_summary(config, origin)}",
        t("advanced.destination"),
        f"    ┗> {profile_summary(config, destination)}",
        t("advanced.tables"),
        f"    ┗> {', '.join(tables) if tables else t('advanced.not_selected')}",
        t("advanced.where"),
        f"    ┗> {where_text}",
        t("advanced.rows"),
        f"    ┗> {rows_text}",
        t("advanced.engine"),
        f"    ┗> {mode}",
    ])


def interactive_advanced_sync(paths: AppPaths) -> int:
    config = load_config(paths)
    origin = config.get("defaults", {}).get("origin", "")
    destination = config.get("defaults", {}).get("destination", "")
    tables = read_last_tables(paths, config)
    where_clause = ""
    insert_missing = False
    mode = "python"
    backup_mode = "none"
    while True:
        choice = select_option(
            t("advanced.title"),
            advanced_menu_options(config, origin, destination, tables, where_clause, insert_missing, mode, backup_mode),
            console=console,
        )
        if choice == "back":
            return MENU_BACK
        if choice == "origin":
            selected = choose_profile(config, t("advanced.origin.title"), origin)
            if selected != "back":
                origin = selected
        elif choice == "destination":
            selected = choose_profile(config, t("advanced.destination.title"), destination)
            if selected != "back":
                destination = selected
        elif choice == "tables":
            selected_tables = read_tables_input()
            if selected_tables is not None:
                tables = selected_tables
        elif choice == "where":
            where_clause = normalize_where_clause(input(t("advanced.where.prompt")))
            if where_clause and mode != "python":
                mode = "python"
        elif choice == "rows":
            row_choice = select_option(
                t("advanced.rows"),
                [
                    MenuOption(t("advanced.rows.all_label"), "all", t("advanced.rows.all_description")),
                    MenuOption(t("advanced.rows.missing_label"), "missing", t("advanced.rows.missing_description")),
                    MenuOption(t("menu.back"), "back"),
                ],
                console=console,
            )
            if row_choice != "back":
                insert_missing = row_choice == "missing"
                if insert_missing and mode != "python":
                    mode = "python"
        elif choice == "mode":
            mode_choice = select_option(
                t("advanced.engine"),
                advanced_mode_options(where_clause, insert_missing),
                console=console,
            )
            if mode_choice != "back":
                mode = mode_choice
        elif choice == "run":
            if not origin or not destination or not tables:
                console.print(f"[red]{t('error')}[/] {t('advanced.run.missing')}")
                pause_after_action()
                continue
            console.print(f"\n[bold]{t('advanced.run.summary')}[/]")
            console.print(format_advanced_sync_state(config, origin, destination, tables, where_clause, insert_missing, mode, backup_mode))
            if not confirm(t("prompt.confirm")):
                return 1
            effective_mode = "python" if where_clause or insert_missing else mode
            return cmd_sync(paths, argparse.Namespace(tables=tables, file=None, origin=origin, destination=destination, last=False, mode=effective_mode, backup=backup_mode, where=where_clause, insert_missing=insert_missing, yes=True, dry_run=False))


def interactive_sync(paths: AppPaths) -> int:
    config = load_config(paths)
    origin = choose_profile(
        config,
        t("menu.sync.title"),
        config.get("defaults", {}).get("origin", ""),
        footer=format_sync_context(step="origin"),
    )
    if origin == "back":
        return MENU_BACK
    destination = choose_profile(
        config,
        t("menu.sync.title"),
        config.get("defaults", {}).get("destination", ""),
        footer=format_sync_context(origin=origin, step="destination"),
    )
    if destination == "back":
        return MENU_BACK
    last = read_last_tables(paths, config)
    table_source = "manual"
    if last:
        table_source = select_option(
            t("menu.sync.title"),
            [
                MenuOption(t("menu.use_last", tables=", ".join(last)), "last"),
                MenuOption(t("menu.enter_tables"), "manual"),
                MenuOption(t("menu.back"), "back"),
            ],
            console=console,
            footer=format_sync_context(origin=origin, destination=destination, step="tables"),
        )
    if table_source == "back":
        return MENU_BACK
    if table_source == "last":
        tables = last
    else:
        console.print(Panel(format_sync_context(origin=origin, destination=destination, step="tables"), title=t("menu.sync.title"), border_style="cyan"))
        tables = read_tables_input()
        if tables is None:
            return MENU_BACK
    console.print(Panel(format_sync_context(origin=origin, destination=destination, tables=tables, mode="auto"), title=t("menu.sync.summary"), border_style="cyan"))
    backup = "none"
    console.print(f"{t('prompt.confirm')}: {origin} → {destination} | {', '.join(tables)} | mode=auto")
    if not confirm(t("prompt.confirm")):
        return 1
    return cmd_sync(paths, argparse.Namespace(tables=tables, file=None, origin=origin, destination=destination, last=False, mode="auto", backup=backup, where=None, insert_missing=False, yes=False))


def interactive_db(paths: AppPaths) -> int:
    while True:
        choice = select_option(
            t("menu.databases"),
            [
                MenuOption(t("db.list"), "list"),
                MenuOption(t("db.add"), "add"),
                MenuOption(t("db.edit_action"), "edit"),
                MenuOption(t("db.test_action"), "test"),
                MenuOption(t("db.remove_action"), "remove"),
                MenuOption(t("menu.back"), "back"),
            ],
            console=console,
        )
        if choice == "back":
            return 0
        if choice == "list":
            status = cmd_db(paths, argparse.Namespace(db_command="list"))
        elif choice == "add":
            status = cmd_db(paths, argparse.Namespace(db_command="add", tag=None))
        elif choice == "edit":
            config = load_config(paths)
            tag = choose_profile(config, t("db.edit"), config.get("defaults", {}).get("destination", ""))
            status = 0 if tag == "back" else cmd_db(paths, argparse.Namespace(db_command="edit", tag=tag))
        elif choice == "test":
            config = load_config(paths)
            tag = choose_profile(config, t("db.test"), config.get("defaults", {}).get("origin", ""))
            status = 0 if tag == "back" else cmd_db(paths, argparse.Namespace(db_command="test", tag=tag))
        elif choice == "remove":
            config = load_config(paths)
            tag = choose_profile(config, t("db.remove"), "")
            status = 0 if tag == "back" else cmd_db(paths, argparse.Namespace(db_command="remove", tag=tag))
        else:
            status = 0
        pause_after_action()


def interactive_defaults(paths: AppPaths) -> int:
    config = load_config(paths)
    origin = choose_profile(config, "Origem padrão", config.get("defaults", {}).get("origin", ""))
    if origin == "back":
        return 0
    destination = choose_profile(config, "Destino padrão", config.get("defaults", {}).get("destination", ""))
    if destination == "back":
        return 0
    return cmd_db(paths, argparse.Namespace(db_command="set-defaults", origin=origin, destination=destination))


def interactive_client(paths: AppPaths) -> int:
    while True:
        choice = select_option(
            t("menu.client"),
            [
                MenuOption(t("client.status"), "status"),
                MenuOption(t("client.install"), "install"),
                MenuOption(t("client.remove"), "remove"),
                MenuOption(t("menu.back"), "back"),
            ],
            console=console,
        )
        if choice == "back":
            return 0
        if choice == "install":
            status = cmd_client(paths, argparse.Namespace(client_command="install", archive_url=None, sha256=None, yes=False))
        elif choice == "remove":
            status = cmd_client(paths, argparse.Namespace(client_command="remove"))
        else:
            status = cmd_client(paths, argparse.Namespace(client_command="status"))
        pause_after_action()


def interactive_logs(paths: AppPaths) -> int:
    choice = select_option(
        t("menu.logs"),
        [
            MenuOption(t("logs.path"), "path"),
            MenuOption(t("logs.tail"), "tail"),
            MenuOption(t("logs.open"), "open"),
            MenuOption(t("logs.clear"), "clear"),
            MenuOption(t("menu.back"), "back"),
        ],
        console=console,
    )
    if choice == "back":
        return 0
    status = cmd_logs(paths, argparse.Namespace(logs_command=choice, lines=40))
    pause_after_action()
    return status


def confirm(question: str) -> bool:
    answer = input(f"{question} [{t('prompt.yes_no')}] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
