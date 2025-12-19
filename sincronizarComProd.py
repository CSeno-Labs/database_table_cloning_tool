import mysql.connector
import subprocess
import os
import sys
import csv
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================

MYSQL_BIN_PATH = r"C:\xampp\mysql\bin"
MYSQLDUMP_EXE = os.path.join(MYSQL_BIN_PATH, "mysqldump.exe")
MYSQL_EXE = os.path.join(MYSQL_BIN_PATH, "mysql.exe")
CSV_FILE = "tabelas_puxar.csv"

# Produção (RDS)
PROD_CONFIG = {
    'host': '',
    'user': '',
    'password': '',
    'database': '',
    'port': 3306,
    'charset': 'latin1' 
}

# Desenvolvimento (Local)
DEV_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': '',
    'port': 3306,
    'charset': 'latin1'
}

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def load_tables_from_csv(filename):
    """Lê o arquivo CSV e retorna uma lista de tabelas."""
    tables = []
    
    if not os.path.exists(filename):
        print(f"   [AVISO] Arquivo '{filename}' não encontrado!")
        print(f"   Criando um arquivo de exemplo para você...")
        try:
            with open(filename, 'w') as f:
                f.write(".\n#adicione_suas_tabelas_aqui")
        except:
            pass
        return []

    print(f"   > Lendo tabelas de '{filename}'...")
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Lê linha por linha
            for line in f:
                line = line.strip()
                # Ignora linhas vazias ou comentários (#)
                if not line or line.startswith('#'):
                    continue
                
                # Suporta separação por vírgula ou ponto e vírgula caso o usuário faça isso
                parts = line.replace(';', ',').split(',')
                for p in parts:
                    t = p.strip()
                    if t:
                        tables.append(t)
        return tables
    except Exception as e:
        print(f"   [ERRO] Falha ao ler arquivo CSV: {e}")
        return []

def get_connection(config):
    return mysql.connector.connect(
        host=config['host'],
        user=config['user'],
        password=config['password'],
        database=config['database'],
        port=config['port'],
        charset=config['charset']
    )

def sanitize_collation(collation):
    """Traduz collations do MySQL 8.0 (Prod) para MariaDB (Local) se necessário."""
    if not collation: return None
    if '0900_ai_ci' in collation:
        return collation.replace('0900_ai_ci', 'general_ci')
    return collation

def get_table_details(config, table_name):
    """Retorna dicionário com detalhes da coluna: { 'coluna': {'type': 'int', 'collation': 'latin1...'} }"""
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
    except mysql.connector.Error as err:
        print(f"   [!] Erro ao ler estrutura de {table_name}: {err}")
        return {}

def sync_structure(table):
    print(f"   > Verificando estrutura de '{table}'...")
    
    prod_cols = get_table_details(PROD_CONFIG, table)
    if not prod_cols:
        print("   [!] Tabela não encontrada na produção ou erro de conexão.")
        return False

    dev_cols = get_table_details(DEV_CONFIG, table)
    
    if not dev_cols:
        print("   > Tabela não existe no local. Será criada inteira pelo dump.")
        return True

    missing_cols = [col for col in prod_cols if col not in dev_cols]

    if not missing_cols:
        print("   > Estrutura OK.")
        return True

    try:
        conn_dev = get_connection(DEV_CONFIG)
        cursor_dev = conn_dev.cursor()
        
        for col in missing_cols:
            details = prod_cols[col]
            col_type = details['type']
            raw_collation = details['collation']
            safe_collation = sanitize_collation(raw_collation)
            
            if safe_collation:
                print(f"   [+] Add coluna: {col} ({col_type}) COLLATE {safe_collation}")
                sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_type} COLLATE {safe_collation} NULL"
            else:
                print(f"   [+] Add coluna: {col} ({col_type})")
                sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_type} NULL"
                
            cursor_dev.execute(sql)
            
        conn_dev.commit()
        conn_dev.close()
        print("   > Estrutura atualizada com sucesso.")
        return True
    except mysql.connector.Error as err:
        print(f"   [ERROR] Falha ao alterar estrutura: {err}")
        return False

def sync_data(table):
    print(f"   > Sincronizando dados de '{table}'...")
    temp_sql = "temp_transaction.sql"
    
    try:
        with open(temp_sql, "w") as f:
            f.write("SET FOREIGN_KEY_CHECKS=0;\n")
            f.write("SET autocommit=0;\n")
            f.write("START TRANSACTION;\n")
            f.write(f"DELETE FROM {table};\n")
        
        dump_cmd = [
            MYSQLDUMP_EXE,
            "-h", PROD_CONFIG['host'],
            "-u", PROD_CONFIG['user'],
            f"-p{PROD_CONFIG['password']}",
            "--no-create-info",
            "--complete-insert", 
            "--skip-add-locks",
            "--skip-comments",
            "--single-transaction",
            "--quick",
            "--default-character-set=latin1", 
            PROD_CONFIG['database'],
            table
        ]

        with open(temp_sql, "a") as f:
            process = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
            if process.returncode != 0:
                print(f"   [ERROR] Erro no mysqldump: {process.stderr}")
                return False

        with open(temp_sql, "a") as f:
            f.write("\nCOMMIT;\n")
            f.write("SET FOREIGN_KEY_CHECKS=1;\n")

        import_cmd = [
            MYSQL_EXE,
            "-h", DEV_CONFIG['host'],
            "-u", DEV_CONFIG['user'],
            f"-p{DEV_CONFIG['password']}",
            "--default-character-set=latin1", 
            DEV_CONFIG['database']
        ]
        
        with open(temp_sql, "r") as f:
            process = subprocess.run(import_cmd, stdin=f, stderr=subprocess.PIPE, text=True)
            
        if process.returncode == 0:
            print(f"   [SUCESSO] Tabela '{table}' sincronizada.")
        else:
            print(f"   [FALHA] Erro na importação. Rollback automático realizado.")
            print(f"   Detalhe: {process.stderr}")

    finally:
        if os.path.exists(temp_sql):
            os.remove(temp_sql)

# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    print(f"==== INICIO DA SINCRONIZACAO INTELIGENTE {datetime.now()} ====")
    print("")

    # Carrega tabelas do arquivo externo
    TABLES = load_tables_from_csv(CSV_FILE)

    if not TABLES:
        print("   [!] Nenhuma tabela encontrada no arquivo CSV.")
    else:
        print(f"   [INFO] Tabelas carregadas: {len(TABLES)}")
        print("")
        
        for table in TABLES:
            print(f"--- Processando: {table} ---")
            if sync_structure(table):
                sync_data(table)
            else:
                print("   [PULANDO] Estrutura inconsistente.")
            print("")

    print(f"==== FIM {datetime.now()} ====")
    input("Pressione Enter para sair...")