from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

from rich.console import Console
from rich.table import Table

from .clients import find_managed_client, find_system_client, resolve_client
from .config import ConfigError, ensure_config, load_config, redact_config, save_config
from .db import test_connection
from .engine import run_dump_sync, run_python_sync
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
    sync.add_argument("-t", "--tables", nargs="+", help="Tabelas para sincronizar")
    sync.add_argument("-f", "--file", help="Arquivo .csv/.txt com tabelas")
    sync.add_argument("--mode", choices=["auto", "dump", "python"], help="Motor de sincronização")

    tables = sub.add_parser("tables", help="Lista tabelas identificadas")
    tables.add_argument("-t", "--tables", nargs="+", help="Tabelas inline")
    tables.add_argument("-f", "--file", help="Arquivo .csv/.txt")

    cfg = sub.add_parser("config", help="Gerencia configuração")
    cfg_sub = cfg.add_subparsers(dest="config_command")
    cfg_sub.add_parser("path", help="Mostra caminho do config")
    cfg_sub.add_parser("show", help="Mostra config com senha mascarada")
    cfg_sub.add_parser("edit", help="Abre config no editor padrão")
    cfg_sub.add_parser("remove", help="Remove config com confirmação")

    client = sub.add_parser("client", help="Gerencia cliente MariaDB/MySQL portátil")
    client_sub = client.add_subparsers(dest="client_command")
    client_sub.add_parser("status", help="Mostra clientes disponíveis")
    client_sub.add_parser("path", help="Mostra pasta do cliente gerenciado")
    install = client_sub.add_parser("install", help="Instala cliente gerenciado explicitamente")
    install.add_argument("--archive-url", help="URL de um .zip/.tar.gz com binários mariadb/mariadb-dump")
    install.add_argument("--yes", action="store_true", help="Não pedir confirmação")
    client_sub.add_parser("remove", help="Remove cliente gerenciado")
    client_sub.add_parser("update", help="Atualiza cliente gerenciado (alias para install)")

    logs = sub.add_parser("logs", help="Gerencia logs")
    logs_sub = logs.add_subparsers(dest="logs_command")
    logs_sub.add_parser("path", help="Mostra caminho dos logs")
    logs_sub.add_parser("clear", help="Limpa logs")

    uninstall = sub.add_parser("uninstall", help="Mostra instruções/atalho de desinstalação")
    uninstall.add_argument("--all", action="store_true", help="Remove também config, cliente gerenciado e logs")
    uninstall.add_argument("--keep-config", action="store_true", help="Remove app e mantém config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
        parser.print_help()
        return 0
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
    for section in ("origem", "destino"):
        db_cfg = config[section]
        if not db_cfg.get("host") or not db_cfg.get("database") or not db_cfg.get("user"):
            console.print(f"[yellow]WARN[/] {section}: host/user/database ainda não configurados")
            continue
        ok, msg = test_connection(db_cfg)
        if ok:
            console.print(f"[green]OK[/] Conexão {section} ({db_cfg.get('alias')}): MySQL/MariaDB {msg}")
        else:
            console.print(f"[red]ERRO[/] Conexão {section}: {msg}")
            failed = True
    return 1 if failed else 0


def collect_tables(args: argparse.Namespace, config: dict | None = None) -> list[str]:
    values: list[str] = []
    if getattr(args, "tables", None):
        values.extend(args.tables)
    if getattr(args, "file", None):
        return parse_tables(values) + [t for t in parse_tables_file(args.file) if t not in parse_tables(values)]
    if not values and config:
        default_file = config.get("sync", {}).get("default_tables_file")
        if default_file and Path(default_file).exists():
            return parse_tables_file(default_file)
    return parse_tables(values)


def cmd_sync(paths: AppPaths, args: argparse.Namespace) -> int:
    config = load_config(paths)
    tables = collect_tables(args, config)
    if not tables:
        console.print("[red]ERRO[/] Nenhuma tabela informada. Use -t ou -f.")
        return 2

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
            result = run_dump_sync(config, table, resolved.client, paths)
        else:
            result = run_python_sync(config, table)
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


def cmd_config(paths: AppPaths, args: argparse.Namespace) -> int:
    sub = args.config_command or "path"
    if sub == "path":
        console.print(str(ensure_config(paths)))
    elif sub == "show":
        console.print_json(json.dumps(redact_config(load_config(paths)), ensure_ascii=False))
    elif sub == "edit":
        path = ensure_config(paths)
        editor = choose_editor()
        return subprocess.call([editor, str(path)])
    elif sub == "remove":
        path = paths.config_file
        if path.exists() and confirm(f"Remover config {path}?"):
            path.unlink()
            console.print("[green]Config removido.[/]")
    return 0


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
    if not args.archive_url:
        console.print("[yellow]Ainda falta configurar a URL oficial dos pacotes MariaDB por plataforma.[/]")
        console.print("Por enquanto, use --archive-url apontando para um .zip/.tar.gz contendo bin/mariadb e bin/mariadb-dump.")
        return 2
    if not args.yes and not confirm(f"Baixar e instalar cliente de {args.archive_url} em {paths.managed_client_dir}?"):
        console.print("Cancelado.")
        return 1
    paths.ensure_dirs()
    archive = paths.cache_dir / Path(args.archive_url).name
    console.print(f"Baixando {args.archive_url}...")
    urlretrieve(args.archive_url, archive)
    target = paths.managed_client_dir / "mariadb" / "current"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(target)
    console.print(f"[green]Cliente instalado em:[/] {target}")
    return 0


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


def confirm(question: str) -> bool:
    answer = input(f"{question} [s/N] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
