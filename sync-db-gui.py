import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
import json
import os
import subprocess
import threading
import time
import mysql.connector
from datetime import datetime
import logging

# Configuração de Aparência
ctk.set_appearance_mode("System")  # "System", "Dark", "Light"
ctk.set_default_color_theme("blue")

# ==============================================================================
# ENGINE DE SINCRONIZAÇÃO (NÚCLEO ADAPTADO)
# ==============================================================================

class SyncEngine:
    def __init__(self, config_path, log_callback):
        self.config_path = config_path
        self.log_callback = log_callback
        self.load_config()

    def load_config(self):
        with open(self.config_path, "r") as f:
            self.config = json.load(f)
        self.settings = self.config["settings"]
        self.origem = self.config["origem"]
        self.destino = self.config["destino"]
        self.mysql_bin = self.settings["mysql_bin_path"]

        mysql_client = self.settings.get("mysql_client", "local")
        if mysql_client == "docker":
            _container = self.settings["docker_container"]
            _bin       = self.settings.get("docker_mysql_bin", "/usr/bin")
            self.mysqldump_base_cmd = ["docker", "exec", "-i", _container,
                                       f"{_bin}/{self.settings.get('docker_mysqldump_cmd', 'mysqldump')}"]
            self.mysql_base_cmd    = ["docker", "exec", "-i", _container,
                                       f"{_bin}/{self.settings.get('docker_mysql_cmd', 'mysql')}"]
        else:
            self.mysqldump_base_cmd = [os.path.join(self.mysql_bin, "mysqldump.exe")]
            self.mysql_base_cmd    = [os.path.join(self.mysql_bin, "mysql.exe")]

    def get_conn(self, cfg):
        params = cfg.copy()
        params.pop('alias', None)
        return mysql.connector.connect(**params)

    def log(self, msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{timestamp}] {msg}\n", level)

    def sync_table(self, table, progress_callback):
        try:
            # 1. Estrutura
            self.log(f"Analisando {table}...")
            
            # Conexão Origem
            conn_ori = self.get_conn(self.origem)
            cur_ori = conn_ori.cursor(dictionary=True)
            cur_ori.execute(f"SHOW FULL COLUMNS FROM {table}")
            origem_cols = {row['Field']: row for row in cur_ori.fetchall()}
            conn_ori.close()

            # Conexão Destino
            needs_creation = False
            try:
                conn_dst = self.get_conn(self.destino)
                cur_dst = conn_dst.cursor(dictionary=True)
                cur_dst.execute(f"SHOW FULL COLUMNS FROM {table}")
                destino_cols = {row['Field']: row for row in cur_dst.fetchall()}
            except:
                needs_creation = True
                destino_cols = {}

            if needs_creation:
                self.log(f"Tabela {table} será criada no destino.")
            else:
                # Sincroniza Colunas
                for col, details in origem_cols.items():
                    if col not in destino_cols:
                        self.log(f"Adicionando coluna {col}...")
                        sql = f"ALTER TABLE {table} ADD COLUMN {col} {details['Type']}"
                        if details['Collation']:
                            coll = details['Collation'].replace('0900_ai_ci', 'general_ci')
                            sql += f" COLLATE {coll}"
                        cur_dst.execute(sql)
                conn_dst.commit()
                conn_dst.close()

            # 2. Dados (Dump & Import)
            temp_sql = os.path.join(os.path.dirname(self.config_path), f"gui_temp_{table}.sql")
            
            # Dump
            self.log(f"Baixando dados de {table}...")
            dump_cmd = self.mysqldump_base_cmd + [
                "-h", self.origem['host'], "-u", self.origem['user'], f"-p{self.origem['password']}"
            ]
            if not needs_creation: dump_cmd.append("--no-create-info")
            dump_cmd.extend(["--complete-insert", "--skip-comments", "--single-transaction", "--quick", "--default-character-set=latin1", self.origem['database'], table])
            
            with open(temp_sql, "w", encoding="utf-8") as f:
                f.write("SET FOREIGN_KEY_CHECKS=0;\nSTART TRANSACTION;\n")
                if not needs_creation: f.write(f"DELETE FROM {table};\n")
            
            with open(temp_sql, "a") as f:
                subprocess.run(dump_cmd, stdout=f, check=True)
            
            with open(temp_sql, "a") as f:
                f.write("\nCOMMIT;\nSET FOREIGN_KEY_CHECKS=1;\n")

            # Import com Feedback
            self.log(f"Importando {table}...")
            file_size = os.path.getsize(temp_sql)
            import_cmd = self.mysql_base_cmd + [
                "-h", self.destino['host'], "-u", self.destino['user'], f"-p{self.destino['password']}",
                "--default-character-set=latin1", self.destino['database']
            ]

            with subprocess.Popen(import_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
                with open(temp_sql, "rb") as f:
                    read_bytes = 0
                    while True:
                        chunk = f.read(1024 * 512)
                        if not chunk: break
                        proc.stdin.write(chunk)
                        read_bytes += len(chunk)
                        progress_callback(read_bytes / file_size)
                proc.stdin.close()
                proc.wait()

            if os.path.exists(temp_sql): os.remove(temp_sql)
            return True
        except Exception as e:
            self.log(f"Erro em {table}: {str(e)}", "ERROR")
            return False

# ==============================================================================
# INTERFACE GRÁFICA (GUI)
# ==============================================================================

class SyncApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("sync-db Pro | Database Cloning Tool")
        self.geometry("900x650")

        # Localização de arquivos
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.script_dir, "config.json")
        
        self.engine = SyncEngine(self.config_path, self.update_terminal)

        # Layout Principal (Grid)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(self.sidebar, text="sync-db", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.pack(pady=20)

        self.btn_sync = ctk.CTkButton(self.sidebar, text="Sincronizar", command=self.show_sync_page)
        self.btn_sync.pack(pady=10, padx=20)

        self.btn_config = ctk.CTkButton(self.sidebar, text="Configurações", command=self.show_config_page)
        self.btn_config.pack(pady=10, padx=20)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar, text="Tema:", anchor="w")
        self.appearance_mode_label.pack(side="bottom", padx=20, pady=(0, 10))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar, values=["Light", "Dark", "System"], command=ctk.set_appearance_mode)
        self.appearance_mode_optionemenu.pack(side="bottom", padx=20, pady=(0, 20))
        self.appearance_mode_optionemenu.set("System")

        # --- MAIN CONTENT ---
        self.main_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        
        self.show_sync_page()

    def clear_main_frame(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

    def show_sync_page(self):
        self.clear_main_frame()
        self.engine.load_config()

        # Header
        header = ctk.CTkLabel(self.main_frame, text=f"Fluxo: {self.engine.origem['alias']} ➔ {self.engine.destino['alias']}", font=ctk.CTkFont(size=18))
        header.pack(pady=10)

        # Input Area
        input_frame = ctk.CTkFrame(self.main_frame)
        input_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(input_frame, text="Tabelas (separadas por vírgula ou arquivo):").pack(pady=5)
        
        self.table_input = ctk.CTkEntry(input_frame, placeholder_text="Ex: aluno, escola, lotacao", width=400)
        self.table_input.pack(side="left", padx=10, pady=10, expand=True, fill="x")

        self.btn_file = ctk.CTkButton(input_frame, text="Abrir Arquivo", width=100, fg_color="transparent", border_width=1, command=self.load_file)
        self.btn_file.pack(side="right", padx=10)

        # Terminal / Logs
        self.terminal = ctk.CTkTextbox(self.main_frame, height=250, font=("Consolas", 12))
        self.terminal.pack(fill="both", padx=20, pady=10, expand=True)
        self.terminal.configure(state="disabled")

        # Progress
        self.progress_label = ctk.CTkLabel(self.main_frame, text="Aguardando início...")
        self.progress_label.pack()
        
        self.progress_bar = ctk.CTkProgressBar(self.main_frame)
        self.progress_bar.pack(fill="x", padx=40, pady=10)
        self.progress_bar.set(0)

        # Action Buttons
        self.btn_start = ctk.CTkButton(self.main_frame, text="INICIAR SINCRONIZAÇÃO", height=50, font=ctk.CTkFont(size=16, weight="bold"), command=self.start_sync_thread)
        self.btn_start.pack(pady=20)

    def show_config_page(self):
        self.clear_main_frame()
        self.engine.load_config()

        scroll_frame = ctk.CTkScrollableFrame(self.main_frame, label_text="Configurações do Sistema")
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Exemplo simples de editor de config
        self.entries = {}
        
        def add_section(name, data):
            ctk.CTkLabel(scroll_frame, text=name.upper(), font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))
            for key, val in data.items():
                row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=key, width=100, anchor="w").pack(side="left")
                entry = ctk.CTkEntry(row, width=300)
                entry.insert(0, str(val))
                entry.pack(side="right", expand=True, fill="x")
                self.entries[f"{name}.{key}"] = entry

        add_section("origem", self.engine.origem)
        add_section("destino", self.engine.destino)
        add_section("settings", self.engine.settings)

        ctk.CTkButton(self.main_frame, text="Salvar Configurações", command=self.save_config).pack(pady=10)

    def save_config(self):
        for key, entry in self.entries.items():
            sec, k = key.split(".")
            val = entry.get()
            if k in ["port"]:
                val = int(val)
            self.engine.config[sec][k] = val
        
        with open(self.config_path, "w") as f:
            json.dump(self.engine.config, f, indent=4)
        messagebox.showinfo("Sucesso", "Configurações salvas!")

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("Arquivos de Texto", "*.csv *.txt")])
        if path:
            with open(path, "r") as f:
                content = f.read().replace("\n", ",").replace(";", ",")
                self.table_input.delete(0, tk.END)
                self.table_input.insert(0, content)

    def update_terminal(self, msg, level="INFO"):
        self.terminal.configure(state="normal")
        color = "white" if level == "INFO" else "red"
        self.terminal.insert("end", msg)
        self.terminal.see("end")
        self.terminal.configure(state="disabled")

    def update_progress(self, value):
        self.progress_bar.set(value)

    def start_sync_thread(self):
        tables_raw = self.table_input.get()
        if not tables_raw:
            # Tenta pegar do CSV padrão se estiver vazio
            path_default = os.path.join(self.script_dir, self.engine.settings["default_csv_file"])
            if os.path.exists(path_default):
                with open(path_default, "r") as f: tables_raw = f.read().replace("\n", ",")
            else:
                messagebox.showwarning("Aviso", "Informe as tabelas!")
                return

        tables = [t.strip() for t in tables_raw.replace(";", ",").split(",") if t.strip()]
        
        self.btn_start.configure(state="disabled", text="PROCESSANDO...")
        threading.Thread(target=self.run_sync, args=(tables,), daemon=True).start()

    def run_sync(self, tables):
        total = len(tables)
        self.update_terminal(f"Iniciando sincronização de {total} tabelas...\n")
        
        for i, table in enumerate(tables, 1):
            self.progress_label.configure(text=f"Processando {i}/{total}: {table}")
            success = self.engine.sync_table(table, self.update_progress)
            if success:
                self.update_terminal(f"✓ {table} concluída.\n")
            else:
                self.update_terminal(f"✗ Erro em {table}.\n", "ERROR")
            
        self.update_terminal("\n--- PROCESSO FINALIZADO ---\n")
        self.progress_label.configure(text="Sincronização concluída!")
        self.progress_bar.set(1)
        self.btn_start.configure(state="normal", text="INICIAR SINCRONIZAÇÃO")
        messagebox.showinfo("Fim", "Sincronização concluída com sucesso!")

if __name__ == "__main__":
    app = SyncApp()
    app.mainloop()
