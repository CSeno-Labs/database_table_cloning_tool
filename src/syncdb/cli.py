from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .clients import find_managed_client, find_system_client, resolve_client
from .config import ConfigError, ensure_config, load_config, profile_tag, redact_config, resolve_profile_pair, save_config, sync_runtime_config
from .db import test_connection
from .engine import run_dump_sync, run_python_sync
from .managed_client import ManagedClientError, install_managed_client, resolve_default_package
from .paths import AppPaths
from .tables import parse_tables, parse_tables_file

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sync-db", description="Sincronizador de tabelas MySQL/MariaDB")
    parser.add_argument("--config", help="Caminho alternativo para config.json")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Cria config padrão na pasta do usuário")
    sub.add_parser("doctor", help="Diagnostica config, clientes e conexões")

    sync = sub.add_parser("sync", help="Sincroniza tabelas")
    add_table_args(sync)
    sync.add_argument("-o", "--origin", help="Tag do banco de origem")
    sync.add_argument("-d", "--destination", help="Tag do banco de destino")
    sync.add_argument("--last", action="store_true", help="Usa as últimas tabelas sincronizadas")
    sync.add_argument("--mode", choices=["auto", "dump", "managed-dump", "system-dump", "python"], help="Motor de sincronização")

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
    commands = {"init", "doctor", "sync", "tables", "config", "db", "client", "logs", "uninstall"}
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
        paths = AppPaths(config_dir=cfg_path.parent, data_dir=paths.data_dir, state_dir=paths.state_dir, cache_dir=paths.cache_dir)

    try:
        return dispatch(args, parser, paths)
    except ConfigError as exc:
        console.print(f"[red]ERRO[/] {exc}")
        console.print("Dica: rode `sync-db config path` e abra o arquivo no editor. Em JSON, barras invertidas precisam ser escapadas como `\\`.")
        return 2


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, paths: AppPaths) -> int:
    if not args.command:
        return run_interactive_menu(paths)
    if args.command == "init":
        return cmd_init(paths)
    if args.command == "doctor":
        return cmd_doctor(paths)
    if args.command == "sync":
        return cmd_sync(paths, args)
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


def cmd_init(paths: AppPaths) -> int:
    path = ensure_config(paths)
    console.print(f"[green]Config pronto:[/] {path}")
    console.print("Edite esse arquivo e depois rode: sync-db doctor")
    return 0


def cmd_doctor(paths: AppPaths) -> int:
    path = ensure_config(paths)
    config = load_config(paths)
    console.print(f"[green]OK[/] Config: {path}")

    managed = find_managed_client(paths, config["client"].get("vendor", "mariadb"))
    system = find_system_client(config["client"].get("vendor", "mariadb"))
    if managed:
        console.print(f"[green]OK[/] Cliente gerenciado: {managed.describe()}")
    else:
        console.print(f"[yellow]WARN[/] Cliente gerenciado não instalado. Rode: sync-db client install")
    if system:
        console.print(f"[green]OK[/] Cliente do sistema: {system.describe()}")
    else:
        console.print("[yellow]WARN[/] Cliente dump do sistema não encontrado no PATH")
    console.print("[green]OK[/] Engine Python disponível")

    resolved = resolve_client(paths, config["client"].get("mode", "auto"), config["client"].get("preferred_source", "managed"), config["client"].get("vendor", "mariadb"))
    console.print(f"Motor recomendado: [bold]{resolved.kind}[/] ({resolved.reason})")

    failed = False
    profiles = config.get("profiles", {})
    if not profiles:
        console.print("[yellow]WARN[/] Nenhum banco cadastrado. Rode: sync-db db add")
    for tag, db_cfg in profiles.items():
        if not db_cfg.get("host") or not db_cfg.get("database") or not db_cfg.get("user"):
            console.print(f"[yellow]WARN[/] {tag}: host/user/database ainda não configurados")
            continue
        ok, msg = test_connection(db_cfg)
        if ok:
            console.print(f"[green]OK[/] Conexão {tag} ({db_cfg.get('label')}): MySQL/MariaDB {msg}")
        else:
            console.print(f"[red]ERRO[/] Conexão {tag}: {msg}")
            failed = True
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
        console.print(f"\n[bold]Sincronizando {table}[/]")
        if resolved.kind == "dump" and resolved.client:
            result = run_dump_sync(runtime_config, table, resolved.client, paths)
        else:
            result = run_python_sync(runtime_config, table)
        results.append(result)
        if result.ok:
            console.print(f"[green]OK[/] {table} ({result.engine}) rows={result.rows}")
        else:
            console.print(f"[red]FALHOU[/] {table}: {result.message}")

    table = Table(title="Resumo")
    table.add_column("Tabela")
    table.add_column("Status")
    table.add_column("Engine")
    table.add_column("Linhas")
    for result in results:
        table.add_row(result.table, "OK" if result.ok else "FALHOU", result.engine, "" if result.rows is None else str(result.rows))
    console.print(table)
    return 0 if all(r.ok for r in results) else 1


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


def cmd_db_list(config: dict) -> int:
    table = Table(title="Bancos cadastrados")
    table.add_column("Tag")
    table.add_column("Label")
    table.add_column("Host")
    table.add_column("Database")
    table.add_column("Uso")
    defaults = config.get("defaults", {})
    for tag, profile in config.get("profiles", {}).items():
        marks = []
        if defaults.get("origin") == tag:
            marks.append("origem padrão")
        if defaults.get("destination") == tag:
            marks.append("destino padrão")
        if not profile.get("allow_as_destination", True):
            marks.append("source_only")
        table.add_row(tag, profile.get("label", ""), profile.get("host", ""), profile.get("database", ""), ", ".join(marks))
    console.print(table)
    return 0


def cmd_db_add(paths: AppPaths, config: dict, tag: str | None, *, editing: bool = False) -> int:
    profiles = config.setdefault("profiles", {})
    if not tag:
        tag = profile_tag(input("Tag do banco: "))
    tag = profile_tag(tag)
    current = profiles.get(tag, {}) if editing else {}
    if editing and tag not in profiles:
        console.print(f"[red]ERRO[/] Banco não encontrado: {tag}")
        return 2
    profile = {
        "label": ask("Rótulo amigável", current.get("label", tag)),
        "host": ask("Host", current.get("host", "")),
        "port": int(ask("Porta", str(current.get("port", 3306))) or 3306),
        "user": ask("Usuário", current.get("user", "")),
        "password": ask("Senha", current.get("password", "")),
        "database": ask("Banco/database", current.get("database", "")),
        "charset": ask("Charset", current.get("charset", "latin1")),
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


def ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def confirm_default(question: str, default: bool) -> bool:
    suffix = "S/n" if default else "s/N"
    answer = input(f"{question} [{suffix}] ").strip().lower()
    if not answer:
        return default
    return answer in {"s", "sim", "y", "yes"}


def cmd_client(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.client_command or "status"
    if sub == "status":
        managed = find_managed_client(paths)
        system = find_system_client()
        console.print(f"Pasta cliente gerenciado: {paths.managed_client_dir}")
        console.print(f"Cliente gerenciado: {managed.describe() if managed else 'não instalado'}")
        console.print(f"Cliente do sistema: {system.describe() if system else 'não encontrado'}")
        console.print("Engine Python: disponível")
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


def run_interactive_menu(paths: AppPaths) -> int:
    ensure_config(paths)
    while True:
        console.print("\n[bold]Menu sync-db[/]")
        console.print("[1] Sincronizar tabelas")
        console.print("[2] Bancos / conexões")
        console.print("[3] Configurações padrão")
        console.print("[4] Doctor / diagnóstico")
        console.print("[5] Cliente MariaDB gerenciado")
        console.print("[6] Logs")
        console.print("[7] Desinstalar sync-db")
        console.print("[0] Sair")
        choice = input("Escolha: ").strip()
        if choice == "0":
            return 0
        if choice == "1":
            return interactive_sync(paths)
        if choice == "2":
            return interactive_db(paths)
        if choice == "3":
            return interactive_defaults(paths)
        if choice == "4":
            return cmd_doctor(paths)
        if choice == "5":
            return interactive_client(paths)
        if choice == "6":
            return cmd_logs(paths, argparse.Namespace(logs_command="path"))
        if choice == "7":
            return cmd_uninstall(paths, argparse.Namespace(all=False, keep_config=True))
        console.print("Opção inválida.")


def interactive_sync(paths: AppPaths) -> int:
    config = load_config(paths)
    cmd_db_list(config)
    origin = ask("Origem", config.get("defaults", {}).get("origin", ""))
    destination = ask("Destino", config.get("defaults", {}).get("destination", ""))
    last = read_last_tables(paths, config)
    if last and confirm_default(f"Usar últimas tabelas ({', '.join(last)})?", False):
        tables = last
    else:
        tables = parse_tables([input("Tabelas: ")])
    mode = ask("Modo", config.get("client", {}).get("mode", "auto"))
    console.print(f"Confirmar: {origin} → {destination} | {', '.join(tables)} | modo={mode}")
    if not confirm("Continuar?"):
        return 1
    return cmd_sync(paths, argparse.Namespace(tables=tables, file=None, origin=origin, destination=destination, last=False, mode=mode))


def interactive_db(paths: AppPaths) -> int:
    console.print("[1] Listar bancos")
    console.print("[2] Adicionar banco")
    console.print("[3] Editar banco")
    console.print("[4] Testar banco")
    choice = input("Escolha: ").strip()
    if choice == "2":
        return cmd_db(paths, argparse.Namespace(db_command="add", tag=None))
    if choice == "3":
        return cmd_db(paths, argparse.Namespace(db_command="edit", tag=input("Tag: ").strip()))
    if choice == "4":
        return cmd_db(paths, argparse.Namespace(db_command="test", tag=input("Tag: ").strip() or None))
    return cmd_db(paths, argparse.Namespace(db_command="list"))


def interactive_defaults(paths: AppPaths) -> int:
    config = load_config(paths)
    cmd_db_list(config)
    origin = ask("Origem padrão", config.get("defaults", {}).get("origin", ""))
    destination = ask("Destino padrão", config.get("defaults", {}).get("destination", ""))
    return cmd_db(paths, argparse.Namespace(db_command="set-defaults", origin=origin, destination=destination))


def interactive_client(paths: AppPaths) -> int:
    console.print("[1] Status")
    console.print("[2] Instalar/atualizar MariaDB")
    console.print("[3] Remover MariaDB")
    choice = input("Escolha: ").strip()
    if choice == "2":
        return cmd_client(paths, argparse.Namespace(client_command="install", archive_url=None, sha256=None, yes=False))
    if choice == "3":
        return cmd_client(paths, argparse.Namespace(client_command="remove"))
    return cmd_client(paths, argparse.Namespace(client_command="status"))


def confirm(question: str) -> bool:
    answer = input(f"{question} [s/N] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
