import mysql.connector
import subprocess
import os
import sys
import csv
import time
import argparse
import json
import logging
from datetime import datetime

# ==============================================================================
# CARREGAMENTO DE CONFIGURAÇÕES
# ==============================================================================

# Pega o diretório real onde o script está localizado
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        # Template padrão caso o arquivo suma
        default_config = {
            "settings": {
                "mysql_client": "local",
                "mysql_bin_path": r"C:\\xampp\\mysql\\bin",
                "docker_container": "mysql",
                "docker_mysql_bin": "/usr/bin",
                "docker_mysql_cmd": "mysql",
                "docker_mysqldump_cmd": "mysqldump",
                "default_csv_file": "tabelas_puxar.csv",
                "log_file": "sincronizacao.log"
            },
            "origem": {"alias": "ORIGEM", "host": "", "user": "", "password": "", "database": "", "port": 3306, "charset": "latin1"},
            "destino": {"alias": "DESTINO", "host": "localhost", "user": "root", "password": "", "database": "", "port": 3306, "charset": "latin1"}
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config
    
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

CONFIG = load_config()

# Atalhos para facilidade
MYSQL_CLIENT = CONFIG["settings"].get("mysql_client", "local").lower()
MYSQL_BIN_PATH = CONFIG["settings"].get("mysql_bin_path", r"C:\\xampp\\mysql\\bin")
DOCKER_CONTAINER = CONFIG["settings"].get("docker_container", "mysql")
DOCKER_MYSQL_BIN = CONFIG["settings"].get("docker_mysql_bin", "/usr/bin")
DOCKER_MYSQL_CMD = CONFIG["settings"].get("docker_mysql_cmd", "mysql")
DOCKER_MYSQLDUMP_CMD = CONFIG["settings"].get("docker_mysqldump_cmd", "mysqldump")

MYSQLDUMP_EXE = os.path.join(MYSQL_BIN_PATH, "mysqldump.exe")
MYSQL_EXE = os.path.join(MYSQL_BIN_PATH, "mysql.exe")

# O arquivo CSV padrão e o LOG também ficam na pasta do script para serem centrais
DEFAULT_CSV_FILE = os.path.join(SCRIPT_DIR, CONFIG["settings"]["default_csv_file"])
LOG_FILE = os.path.join(SCRIPT_DIR, CONFIG["settings"]["log_file"])

ORIGEM_CONFIG = CONFIG["origem"]
DESTINO_CONFIG = CONFIG["destino"]

# ==============================================================================
# CONFIGURAÇÃO DE LOGGING
# ==============================================================================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    encoding='utf-8'
)

# Tenta importar rich
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, FileSizeColumn, TransferSpeedColumn
    from rich.table import Table
    from rich.theme import Theme
    
    custom_theme = Theme({
        "info": "cyan", "warning": "yellow", "error": "bold red", 
        "success": "bold green", "header": "bold white", "sql": "dim italic white"
    })
    console = Console(theme=custom_theme)
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ==============================================================================
# FUNÇÕES DE LOG (WRAPPER)
# ==============================================================================

def log_info(msg):
    logging.info(msg)
    if HAS_RICH: console.print(f"[info]ℹ  {msg}[/info]")
    else: print(f"[INFO] {msg}")

def log_success(msg):
    logging.info(f"SUCCESS: {msg}")
    if HAS_RICH: console.print(f"[success]✔  {msg}[/success]")
    else: print(f"[SUCESSO] {msg}")

def log_error(msg):
    logging.error(msg)
    if HAS_RICH: console.print(f"[error]✖  {msg}[/error]")
    else: print(f"[ERRO] {msg}")

def log_warn(msg):
    logging.warning(msg)
    if HAS_RICH: console.print(f"[warning]⚠  {msg}[/warning]")
    else: print(f"[AVISO] {msg}")

def log_header(msg):
    logging.info(f"=== {msg} ===")
    if HAS_RICH: console.print(Panel(msg, style="header", expand=False))
    else: print(f"\n=== {msg} ===\n")

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def load_tables_from_file(filename, create_if_missing=False):
    tables = []
    if not os.path.exists(filename):
        if create_if_missing:
            log_warn(f"Arquivo padrão '{filename}' não encontrado! Criando exemplo...")
            with open(filename, 'w') as f: f.write("#adicione_tabelas_aqui")
            return []
        log_error(f"Arquivo '{filename}' não encontrado.")
        return []

    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                parts = line.replace(';', ',').split(',')
                for p in parts:
                    if p.strip(): tables.append(p.strip())
        return tables
    except Exception as e:
        log_error(f"Falha ao ler arquivo: {e}")
        return []

def get_connection(config):
    conn_params = config.copy()
    conn_params.pop('alias', None)
    return mysql.connector.connect(**conn_params)

def sanitize_collation(collation):
    if not collation: return None
    if '0900_ai_ci' in collation: return collation.replace('0900_ai_ci', 'general_ci')
    return collation

def get_table_details(config, table_name):
    try:
        conn = get_connection(config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SHOW FULL COLUMNS FROM {table_name}")
        rows = cursor.fetchall()
        columns = {}
        for row in rows:
            col_name = row['Field']
            if isinstance(col_name, bytes): col_name = col_name.decode('utf-8')
            col_type = row['Type']
            if isinstance(col_type, bytes): col_type = col_type.decode('utf-8')
            col_collation = row['Collation']
            if isinstance(col_collation, bytes): col_collation = col_collation.decode('utf-8')
            columns[col_name] = {'type': col_type, 'collation': col_collation}
        conn.close()
        return columns
    except: return {}

def sync_structure(table):
    if HAS_RICH: console.print(f"   🔎 Analisando estrutura de [bold cyan]{table}[/]...", style="dim")
    
    origem_cols = get_table_details(ORIGEM_CONFIG, table)
    if not origem_cols:
        log_error(f"Tabela '{table}' não encontrada na origem ({ORIGEM_CONFIG['alias']}).")
        return False, False

    destino_cols = get_table_details(DESTINO_CONFIG, table)
    if not destino_cols:
        log_info(f"Tabela '{table}' nova no destino ({DESTINO_CONFIG['alias']}).")
        return True, True

    missing_cols = [col for col in origem_cols if col not in destino_cols]
    if not missing_cols:
        return True, False

    try:
        conn_dst = get_connection(DESTINO_CONFIG)
        cursor_dst = conn_dst.cursor()
        for col in missing_cols:
            details = origem_cols[col]
            sql = f"ALTER TABLE {table} ADD COLUMN {col} {details['type']}"
            safe_coll = sanitize_collation(details['collation'])
            if safe_coll: sql += f" COLLATE {safe_coll}"
            sql += " NULL"
            log_info(f"Adicionando coluna {col} em {table}")
            cursor_dst.execute(sql)
        conn_dst.commit()
        conn_dst.close()
        return True, False
    except mysql.connector.Error as err:
        log_error(f"Falha ao alterar estrutura: {err}")
        return False, False

def build_dump_cmd(needs_creation, table):
    if MYSQL_CLIENT == "docker":
        mysqldump = f"{DOCKER_MYSQL_BIN}/{DOCKER_MYSQLDUMP_CMD}"
        cmd = ["docker", "exec", "-i", DOCKER_CONTAINER, mysqldump]
    else:
        cmd = [MYSQLDUMP_EXE]

    cmd.extend(["-h", ORIGEM_CONFIG['host'], "-u", ORIGEM_CONFIG['user'], f"-p{ORIGEM_CONFIG['password']}"])
    if not needs_creation: cmd.append("--no-create-info")
    cmd.extend([
        "--complete-insert", "--skip-add-locks", "--skip-comments",
        "--single-transaction", "--quick", "--default-character-set=latin1",
        ORIGEM_CONFIG['database'], table
    ])
    return cmd

def build_import_cmd():
    if MYSQL_CLIENT == "docker":
        mysql = f"{DOCKER_MYSQL_BIN}/{DOCKER_MYSQL_CMD}"
        cmd = ["docker", "exec", "-i", DOCKER_CONTAINER, mysql]
    else:
        cmd = [MYSQL_EXE]

    cmd.extend([
        "-h", DESTINO_CONFIG['host'], "-u", DESTINO_CONFIG['user'],
        f"-p{DESTINO_CONFIG['password']}", "--default-character-set=latin1",
        DESTINO_CONFIG['database']
    ])
    return cmd

def validate_mysql_client():
    if MYSQL_CLIENT == "docker":
        return True
    if not os.path.exists(MYSQLDUMP_EXE) or not os.path.exists(MYSQL_EXE):
        log_error(
            "Cliente MySQL local não encontrado. Verifique 'mysql_bin_path' "
            "ou mude 'mysql_client' para 'docker' no config.json."
        )
        return False
    return True

def sync_data(table, needs_creation=False):
    temp_sql = f"temp_{table}.sql"
    header_sql = "SET FOREIGN_KEY_CHECKS=0;\nSET autocommit=0;\nSTART TRANSACTION;\n"
    if not needs_creation: header_sql += f"DELETE FROM {table};\n"
        
    try:
        with open(temp_sql, "w", encoding='utf-8') as f: f.write(header_sql)
        
        dump_cmd = build_dump_cmd(needs_creation, table)

        # Dump
        if HAS_RICH:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
                progress.add_task(f"Baixando [cyan]{table}[/]...", total=None)
                with open(temp_sql, "a") as f:
                    subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
        else:
            with open(temp_sql, "a") as f: subprocess.run(dump_cmd, stdout=f)

        with open(temp_sql, "a", encoding='utf-8') as f: f.write("\nCOMMIT;\nSET FOREIGN_KEY_CHECKS=1;\n")

        # Import
        file_size = os.path.getsize(temp_sql)
        import_cmd = build_import_cmd()

        if HAS_RICH:
            with subprocess.Popen(import_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                with Progress(SpinnerColumn(), TextColumn("[blue]{task.fields[table_name]}"), BarColumn(bar_width=None), "[progress.percentage]{task.percentage:>3.0f}%", "•", FileSizeColumn(), "•", TransferSpeedColumn(), console=console) as progress:
                    task_id = progress.add_task("Import", total=file_size, table_name=f"Importando {table}")
                    with open(temp_sql, "rb") as f:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk: break
                            proc.stdin.write(chunk)
                            proc.stdin.flush()
                            progress.update(task_id, advance=len(chunk))
                proc.stdin.close()
                return_code = proc.wait()
                stderr = proc.stderr.read().decode('utf-8', errors='ignore')
        else:
            with open(temp_sql, "r") as f:
                p = subprocess.run(import_cmd, stdin=f, stderr=subprocess.PIPE, text=True)
                return_code, stderr = p.returncode, p.stderr

        return return_code == 0
    except Exception as e:
        log_error(f"Erro em {table}: {e}")
        return False
    finally:
        if os.path.exists(temp_sql): os.remove(temp_sql)

# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sync-db: Sincronizador MySQL")
    parser.add_argument('-t', '--tables', nargs='+', help="Tabelas manuais")
    parser.add_argument('-f', '--file', help="Arquivo de tabelas")
    parser.add_argument('-s', '--showtables', action='store_true', help="Apenas listar")
    parser.add_argument('-l', '--logs', action='store_true', help="Ver as últimas entradas do log")
    args = parser.parse_args()

    # === MODO VISUALIZAR LOGS ===
    if args.logs:
        if not os.path.exists(LOG_FILE):
            print(f"Arquivo de log não encontrado em: {LOG_FILE}")
            sys.exit(0)
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-20:] # Pega as últimas 20 linhas
        
        if HAS_RICH:
            from rich.syntax import Syntax
            content = "".join(last_lines)
            console.print(Panel(f"Últimas 20 entradas de: [bold]{LOG_FILE}[/]", style="info"))
            console.print(Syntax(content, "log", theme="monokai", word_wrap=True))
        else:
            print(f"--- ÚLTIMAS ENTRADAS DE {LOG_FILE} ---")
            print("".join(last_lines))
        sys.exit(0)

    os.system('cls' if os.name == 'nt' else 'clear')
    log_header(f"SINC: {ORIGEM_CONFIG['alias']} ➔ {DESTINO_CONFIG['alias']}")
    if not validate_mysql_client():
        sys.exit(1)

    TABLES = []
    sources = []
    if args.tables:
        TABLES.extend(args.tables); sources.append("CLI")
    if args.file:
        t = load_tables_from_file(args.file); TABLES.extend(t); sources.append(args.file)
    if not args.tables and not args.file:
        t = load_tables_from_file(DEFAULT_CSV_FILE, True); TABLES.extend(t); sources.append(DEFAULT_CSV_FILE)

    unique_tables = list(dict.fromkeys(TABLES))
    TABLES = unique_tables

    if args.showtables:
        if HAS_RICH:
            t_p = Table(title="Tabelas Identificadas"); t_p.add_column("#"); t_p.add_column("Tabela")
            for i, tbl in enumerate(TABLES, 1): t_p.add_row(str(i), tbl)
            console.print(t_p)
        else:
            for i, tbl in enumerate(TABLES, 1): print(f"{i}. {tbl}")
        sys.exit(0)

    results = []
    for table in TABLES:
        if HAS_RICH: console.rule(f"[bold]{table}[/bold]")
        start = time.time()
        ok_struct, need_create = sync_structure(table)
        status = "ERRO"
        if ok_struct:
            if sync_data(table, need_create):
                status = "SUCESSO"
                log_success(f"{table} sincronizada.")
            else: status = "ERRO DADOS"
        else: status = "ERRO ESTRUTURA"
        results.append((table, status, f"{time.time()-start:.1f}s"))

    if HAS_RICH and results:
        res = Table(title="Resumo Final"); res.add_column("Tabela"); res.add_column("Status"); res.add_column("Tempo")
        for r in results:
            style = "green" if r[1] == "SUCESSO" else "red"
            res.add_row(r[0], f"[{style}]{r[1]}[/]", r[2])
        console.print(res)

    print("")
    if HAS_RICH: console.input("[bold]Enter para sair...[/]")
    else: input("Enter para sair...")
