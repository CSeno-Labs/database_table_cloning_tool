from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .clients import find_managed_client, find_system_client, resolve_client
from .config import ConfigError, ensure_config, load_config, profile_tag, redact_config, resolve_profile_pair, save_config, sync_runtime_config
from .db import test_connection
from .engine import drop_table, run_dump_sync, run_python_sync, run_table_backup
from .interactive import MenuOption, select_option
from .managed_client import ManagedClientError, install_managed_client, resolve_default_package
from .paths import AppPaths
from .tables import parse_tables, parse_tables_file

console = Console()
APP_VERSION = "2.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sync-db", description="Sincronizador de tabelas MySQL/MariaDB")
    parser.add_argument("--version", action="store_true", help="Mostra versão e sai")
    parser.add_argument("--config", help="Caminho alternativo para config.json")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Cria config padrão na pasta do usuário")
    init.add_argument("--quiet", action="store_true", help="Não imprime mensagens informativas")
    sub.add_parser("doctor", help="Diagnostica config, clientes e conexões")

    sync = sub.add_parser("sync", help="Sincroniza tabelas")
    add_table_args(sync)
    sync.add_argument("-o", "--origin", help="Tag do banco de origem")
    sync.add_argument("-d", "--destination", help="Tag do banco de destino")
    sync.add_argument("--last", action="store_true", help="Usa as últimas tabelas sincronizadas")
    sync.add_argument("--mode", choices=["auto", "dump", "managed-dump", "system-dump", "python"], help="Motor de sincronização")
    sync.add_argument("--backup", nargs="?", const="temp", choices=["temp", "keep", "none"], help="Cria backup antes de sobrescrever; sem valor remove ao terminar com sucesso, use --backup keep para manter")

    backup = sub.add_parser("backup", help="Cria backups de tabelas no banco escolhido")
    add_table_args(backup)
    backup.add_argument("-d", "--destination", help="Tag do banco onde o backup será criado")
    backup.add_argument("-y", "--yes", action="store_true", help="Usa nomes sugeridos sem perguntar")

    tables = sub.add_parser("tables", help="Lista tabelas identificadas")
    tables.add_argument("-t", "--tables", nargs="+", help="Tabelas inline")
    tables.add_argument("-f", "--file", help="Arquivo .csv/.txt")

    cfg = sub.add_parser("config", help="Gerencia configuração")
    cfg_sub = cfg.add_subparsers(dest="config_command")
    cfg_sub.add_parser("path", help="Mostra caminho do config")
    cfg_sub.add_parser("show", help="Mostra config com senha mascarada")
    cfg_sub.add_parser("edit", help="Abre config no editor padrão")
    cfg_sub.add_parser("remove", help="Remove config com confirmação")

    db = sub.add_parser("db", help="Gerencia bancos/conexões cadastrados")
    db_sub = db.add_subparsers(dest="db_command")
    db_sub.add_parser("list", help="Lista bancos cadastrados")
    add_db = db_sub.add_parser("add", help="Cadastra banco interativamente")
    add_db.add_argument("tag", nargs="?", help="Tag do banco")
    edit_db = db_sub.add_parser("edit", help="Edita banco interativamente")
    edit_db.add_argument("tag")
    rm_db = db_sub.add_parser("remove", help="Remove banco")
    rm_db.add_argument("tag")
    test_db = db_sub.add_parser("test", help="Testa conexão de um banco")
    test_db.add_argument("tag", nargs="?")
    defaults_db = db_sub.add_parser("set-defaults", help="Define origem/destino padrão")
    defaults_db.add_argument("-o", "--origin", required=True)
    defaults_db.add_argument("-d", "--destination", required=True)

    client = sub.add_parser("client", help="Gerencia cliente MariaDB/MySQL portátil")
    client_sub = client.add_subparsers(dest="client_command")
    client_sub.add_parser("status", help="Mostra clientes disponíveis")
    client_sub.add_parser("path", help="Mostra pasta do cliente gerenciado")
    install = client_sub.add_parser("install", help="Instala cliente gerenciado explicitamente")
    add_client_install_args(install)
    client_sub.add_parser("remove", help="Remove cliente gerenciado")
    update = client_sub.add_parser("update", help="Atualiza cliente gerenciado (alias para install)")
    add_client_install_args(update)

    logs = sub.add_parser("logs", help="Gerencia logs")
    logs_sub = logs.add_subparsers(dest="logs_command")
    logs_sub.add_parser("path", help="Mostra caminho dos logs")
    tail = logs_sub.add_parser("tail", help="Mostra últimas linhas do log")
    tail.add_argument("-n", "--lines", type=int, default=40, help="Quantidade de linhas")
    logs_sub.add_parser("open", help="Abre pasta dos logs")
    logs_sub.add_parser("clear", help="Limpa logs")

    uninstall = sub.add_parser("uninstall", help="Mostra instruções/atalho de desinstalação")
    uninstall.add_argument("--all", action="store_true", help="Remove também config, cliente gerenciado e logs")
    uninstall.add_argument("--keep-config", action="store_true", help="Remove app e mantém config")
    return parser


def add_table_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-t", "--tables", nargs="+", help="Tabelas para sincronizar")
    parser.add_argument("-f", "--file", help="Arquivo .csv/.txt com tabelas")


def add_client_install_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--archive-url", help="URL opcional de um .zip/.tar.gz customizado com binários mariadb/mariadb-dump")
    parser.add_argument("--sha256", help="SHA256 esperado quando usar --archive-url")
    parser.add_argument("--yes", action="store_true", help="Não pedir confirmação")


def normalize_legacy_args(argv: list[str]) -> list[str]:
    """Support the old CLI shape: sync-db -t tabela, -s, -l.

    The new CLI is subcommand-based, but existing users naturally try the old
    flags. Normalize those flags before argparse sees a subcommand position.
    """
    commands = {"init", "doctor", "sync", "backup", "tables", "config", "db", "client", "logs", "uninstall"}
    legacy_flags = {"-t", "--tables", "-f", "--file", "-o", "--origin", "-d", "--destination", "-s", "--showtables", "-l", "--logs"}
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
    parser = build_parser()
    argv = normalize_legacy_args(list(argv) if argv is not None else sys.argv[1:])
    args = parser.parse_args(argv)
    paths = AppPaths.current()
    if args.config:
        cfg_path = Path(args.config).expanduser().resolve()
        base_dir = cfg_path.parent.parent if cfg_path.parent.name == "config" else cfg_path.parent
        paths = AppPaths(config_dir=cfg_path.parent, data_dir=base_dir / "data", state_dir=base_dir / "state", cache_dir=base_dir / "cache")

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


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, paths: AppPaths) -> int:
    if not args.command:
        return run_interactive_menu(paths)
    if args.command == "init":
        return cmd_init(paths, quiet=getattr(args, "quiet", False))
    if args.command == "doctor":
        return cmd_doctor(paths)
    if args.command == "sync":
        return cmd_sync(paths, args)
    if args.command == "backup":
        return cmd_backup(paths, args)
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


def cmd_doctor(paths: AppPaths) -> int:
    path = ensure_config(paths)
    config = load_config(paths)
    console.print(Panel.fit(f"[bold]Config[/]\n{path}", title="sync-db doctor", border_style="green"))

    managed = find_managed_client(paths, config["client"].get("vendor", "mariadb"))
    system = find_system_client(config["client"].get("vendor", "mariadb"))
    clients_table = Table(title="Clientes / motores")
    clients_table.add_column("Item")
    clients_table.add_column("Status")
    clients_table.add_column("Detalhes")
    clients_table.add_row("Cliente gerenciado", "OK" if managed else "WARN", managed.describe() if managed else "não instalado — rode: sync-db client install")
    clients_table.add_row("Cliente do sistema", "OK" if system else "WARN", system.describe() if system else "não encontrado no PATH")
    clients_table.add_row("Engine Python", "OK", "disponível")
    resolved = resolve_client(paths, config["client"].get("mode", "auto"), config["client"].get("preferred_source", "managed"), config["client"].get("vendor", "mariadb"))
    clients_table.add_row("Motor recomendado", resolved.kind, resolved.reason)
    console.print(clients_table)

    failed = False
    profiles = config.get("profiles", {})
    conn_table = Table(title="Conexões")
    conn_table.add_column("Tag")
    conn_table.add_column("Nome")
    conn_table.add_column("Host")
    conn_table.add_column("Database")
    conn_table.add_column("Status")
    conn_table.add_column("Versão / mensagem")
    if not profiles:
        console.print("[yellow]WARN[/] Nenhum banco cadastrado. Rode: sync-db db add")
    for tag, db_cfg in profiles.items():
        if not db_cfg.get("host") or not db_cfg.get("database") or not db_cfg.get("user"):
            conn_table.add_row(tag, db_cfg.get("label", ""), db_cfg.get("host", ""), db_cfg.get("database", ""), "WARN", "host/user/database ainda não configurados")
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
    console.print(f"Fluxo: [bold]{runtime_config['origem']['alias']}[/] → [bold]{runtime_config['destino']['alias']}[/]")
    save_last_tables(paths, config, tables)

    mode = args.mode or config.get("client", {}).get("mode", "auto")
    resolved = resolve_client(paths, mode, config["client"].get("preferred_source", "managed"), config["client"].get("vendor", "mariadb"))
    if resolved.kind == "missing":
        console.print(f"[red]ERRO[/] {resolved.reason}")
        console.print("Opções: sync-db client install | instalar cliente no sistema | --mode python")
        return 1
    console.print(f"Motor: [bold]{resolved.kind}[/] — {resolved.reason}")

    results = []
    for table in tables:
        console.print(f"\n[bold cyan]Sincronizando {table}[/]")
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


def write_sync_log(paths: AppPaths, runtime_config: dict, tables: list[str], engine: str, results: list) -> Path:
    paths.ensure_dirs()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "origin": runtime_config.get("origem", {}).get("alias"),
        "destination": runtime_config.get("destino", {}).get("alias"),
        "origin_host": runtime_config.get("origem", {}).get("host"),
        "destination_host": runtime_config.get("destino", {}).get("host"),
        "tables": tables,
        "engine": engine,
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
        table = Table(title="Cliente MariaDB / MySQL")
        table.add_column("Item")
        table.add_column("Status")
        table.add_column("Detalhes")
        table.add_row("Pasta gerenciada", "OK", str(paths.managed_client_dir))
        table.add_row("Cliente gerenciado", "OK" if managed else "WARN", managed.describe() if managed else "não instalado")
        table.add_row("Cliente do sistema", "OK" if system else "WARN", system.describe() if system else "não encontrado")
        table.add_row("Engine Python", "OK", "disponível")
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
    console.print("Este comando instala o cliente gerenciado explicitamente. O sync nunca baixa cliente escondido.")
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
        options.append(MenuOption("Voltar", "back"))
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
        input("\nPressione Enter para voltar ao menu...")


def run_interactive_menu(paths: AppPaths) -> int:
    ensure_config(paths)
    last_status = 0
    while True:
        choice = select_option(
            "Menu sync-db",
            [
                MenuOption("Sincronizar tabelas", "sync"),
                MenuOption("Backup de tabelas", "backup"),
                MenuOption("Bancos / conexões", "db"),
                MenuOption("Logs", "logs"),
                MenuOption("Mais", "more"),
                MenuOption("Sair", "exit"),
            ],
            console=console,
        )
        if choice in {"exit", "back"}:
            print_exit_banner()
            return last_status
        if choice == "sync":
            last_status = interactive_sync(paths)
            pause_after_action()
        elif choice == "backup":
            last_status = interactive_backup(paths)
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
            "Mais opções",
            [
                MenuOption("Configurações padrão", "defaults"),
                MenuOption("Doctor / diagnóstico", "doctor"),
                MenuOption("Cliente MariaDB gerenciado", "client"),
                MenuOption("Desinstalar sync-db", "uninstall"),
                MenuOption("Voltar", "back"),
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
        elif choice == "client":
            status = interactive_client(paths)
        elif choice == "uninstall":
            status = cmd_uninstall(paths, argparse.Namespace(all=False, keep_config=True))
            pause_after_action()
        else:
            status = 0
        if not sys.stdin.isatty():
            return status


def format_sync_context(*, origin: str = "", destination: str = "", tables: list[str] | None = None, mode: str = "", step: str = "") -> str:
    lines: list[str] = []
    if origin:
        lines.append(f"Origem escolhida: {origin}")
    if destination:
        lines.append(f"Destino escolhido: {destination}")
    if tables:
        lines.append(f"Tabelas escolhidas: {', '.join(tables)}")
    if mode:
        lines.append(f"Motor escolhido: {mode}")
    step_text = {
        "origin": "Escolha o banco de origem",
        "destination": "Escolha o banco de destino",
        "tables": "Escolha as tabelas que serão sincronizadas",
        "mode": "Escolha o motor",
    }.get(step, "")
    if step_text:
        lines.append(step_text)
    return "\n".join(lines)


def interactive_backup(paths: AppPaths) -> int:
    config = load_config(paths)
    destination = choose_profile(config, "Backup de tabelas", config.get("defaults", {}).get("destination", ""), footer="Escolha o banco onde os backups serão criados")
    if destination == "back":
        return 0
    console.print(Panel(f"Banco escolhido: {destination}\nDigite as tabelas que serão copiadas para backup.", title="Backup de tabelas", border_style="cyan"))
    tables = parse_tables([input("Tabelas: ")])
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada.")
        return 2
    console.print("Nomes sugeridos dos backups. Pressione Enter para confirmar ou edite o nome.")
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    selected_names = []
    for table in tables:
        selected_names.append(ask(f"Backup para {table}", suggested_backup_name(table, suffix)))
    args = argparse.Namespace(tables=tables, file=None, destination=destination, yes=True)
    original = suggested_backup_name
    names_iter = iter(selected_names)
    try:
        globals()["suggested_backup_name"] = lambda table, suffix=None: next(names_iter)
        return cmd_backup(paths, args)
    finally:
        globals()["suggested_backup_name"] = original


def interactive_sync(paths: AppPaths) -> int:
    config = load_config(paths)
    origin = choose_profile(
        config,
        "Sincronizando tabelas",
        config.get("defaults", {}).get("origin", ""),
        footer=format_sync_context(step="origin"),
    )
    if origin == "back":
        return 0
    destination = choose_profile(
        config,
        "Sincronizando tabelas",
        config.get("defaults", {}).get("destination", ""),
        footer=format_sync_context(origin=origin, step="destination"),
    )
    if destination == "back":
        return 0
    last = read_last_tables(paths, config)
    table_source = "manual"
    if last:
        table_source = select_option(
            "Sincronizando tabelas",
            [
                MenuOption(f"Usar últimas ({', '.join(last)})", "last"),
                MenuOption("Digitar tabelas", "manual"),
                MenuOption("Voltar", "back"),
            ],
            console=console,
            footer=format_sync_context(origin=origin, destination=destination, step="tables"),
        )
    if table_source == "back":
        return 0
    if table_source == "last":
        tables = last
    else:
        console.print(Panel(format_sync_context(origin=origin, destination=destination, step="tables"), title="Sincronizando tabelas", border_style="cyan"))
        tables = parse_tables([input("Tabelas: ")])
    mode = select_option(
        "Sincronizando tabelas",
        [
            MenuOption("auto", "auto", "recomendado"),
            MenuOption("managed-dump", "managed-dump", "MariaDB gerenciado"),
            MenuOption("system-dump", "system-dump", "cliente do sistema"),
            MenuOption("python", "python", "fallback sem dump"),
            MenuOption("Voltar", "back"),
        ],
        console=console,
        footer=format_sync_context(origin=origin, destination=destination, tables=tables, step="mode"),
    )
    if mode == "back":
        return 0
    console.print(Panel(format_sync_context(origin=origin, destination=destination, tables=tables, mode=mode), title="Resumo da sincronização", border_style="cyan"))
    backup = "none"
    if confirm_default("Criar backup da tabela destino antes de sobrescrever?", False, default_label="(Default: Não)"):
        backup = "keep" if confirm_default("Manter o backup no banco após sincronizar com sucesso?", False) else "temp"
    console.print(f"Confirmar: {origin} → {destination} | {', '.join(tables)} | modo={mode} | backup={backup}")
    if not confirm("Continuar?"):
        return 1
    return cmd_sync(paths, argparse.Namespace(tables=tables, file=None, origin=origin, destination=destination, last=False, mode=mode, backup=backup))


def interactive_db(paths: AppPaths) -> int:
    while True:
        choice = select_option(
            "Bancos / conexões",
            [
                MenuOption("Listar bancos", "list"),
                MenuOption("Adicionar banco", "add"),
                MenuOption("Editar banco", "edit"),
                MenuOption("Testar banco", "test"),
                MenuOption("Remover banco", "remove"),
                MenuOption("Voltar", "back"),
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
            tag = choose_profile(config, "Banco para editar", config.get("defaults", {}).get("destination", ""))
            status = 0 if tag == "back" else cmd_db(paths, argparse.Namespace(db_command="edit", tag=tag))
        elif choice == "test":
            config = load_config(paths)
            tag = choose_profile(config, "Banco para testar", config.get("defaults", {}).get("origin", ""))
            status = 0 if tag == "back" else cmd_db(paths, argparse.Namespace(db_command="test", tag=tag))
        elif choice == "remove":
            config = load_config(paths)
            tag = choose_profile(config, "Banco para remover", "")
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
            "Cliente MariaDB gerenciado",
            [
                MenuOption("Status", "status"),
                MenuOption("Instalar/atualizar MariaDB", "install"),
                MenuOption("Remover MariaDB", "remove"),
                MenuOption("Voltar", "back"),
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
        "Logs",
        [
            MenuOption("Mostrar caminho", "path"),
            MenuOption("Ver últimas linhas", "tail"),
            MenuOption("Abrir pasta", "open"),
            MenuOption("Limpar logs", "clear"),
            MenuOption("Voltar", "back"),
        ],
        console=console,
    )
    if choice == "back":
        return 0
    status = cmd_logs(paths, argparse.Namespace(logs_command=choice, lines=40))
    pause_after_action()
    return status


def confirm(question: str) -> bool:
    answer = input(f"{question} [s/N] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
