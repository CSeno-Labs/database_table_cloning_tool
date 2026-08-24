"""Small, explicit catalog for sync-db user-facing text.

SQL, table names, column names, profile tags, and other user identifiers must be
passed as interpolation values; translations never alter them.
"""
from __future__ import annotations

from contextvars import ContextVar

DEFAULT_LANGUAGE = "pt-BR"
SUPPORTED_LANGUAGES = ("pt-BR", "en")
_current_language: ContextVar[str] = ContextVar("syncdb_language", default=DEFAULT_LANGUAGE)


CATALOG: dict[str, dict[str, str]] = {
    "pt-BR": {
        "app.description": "Sincronizador de tabelas MySQL/MariaDB",
        "help.version": "Mostra versão e sai",
        "help.config": "Caminho alternativo para config.json",
        "help.language": "Idioma da interface nesta execução (não salva a configuração)",
        "help.schema": "Analisa e sincroniza estrutura de tabelas",
        "help.schema.diff": "Mostra diferenças de estrutura sem alterar nada",
        "help.schema.copy": "Copia estrutura da origem; pode alterar e remover extras",
        "help.schema.update": "Atualiza estrutura preservando extras do destino",
        "help.schema.recreate": "Recria tabela no destino a partir da origem",
        "help.init": "Cria config padrão na pasta do usuário",
        "help.doctor": "Diagnostica config, clientes e conexões",
        "help.update": "Atualiza o sync-db a partir da branch main do GitHub",
        "help.sync": "Sincroniza tabelas",
        "help.backup": "Cria backups de tabelas no banco escolhido",
        "help.tables": "Lista tabelas identificadas",
        "help.config_cmd": "Gerencia configuração",
        "help.db": "Gerencia bancos/conexões cadastrados",
        "help.client": "Gerencia cliente MariaDB/MySQL portátil",
        "help.logs": "Gerencia logs",
        "help.uninstall": "Mostra instruções/atalho de desinstalação",
        "help.tables_arg": "Tabelas para sincronizar",
        "help.file_arg": "Arquivo .csv/.txt com tabelas",
        "help.origin": "Tag do banco modelo/origem",
        "help.destination": "Tag do banco que será alterado/comparado",
        "help.yes_schema": "Confirma a aplicação do plano de estrutura",
        "help.verbose": "Mostra tempos detalhados de leitura",
        "help.plan": "Mostra plano de alteração sem modificar o banco",
        "help.plan_action": "Plano para copiar estrutura ou atualizar preservando extras",
        "help.sql": "Inclui bloco SQL FINAL após o plano",
        "help.no_sql": "Oculta SQL abaixo de cada operação",
        "help.sql_only": "Imprime somente o SQL do plano",
        "help.save": "Salva plano documentado e executável em arquivo SQL",
        "menu.main": "Menu sync-db",
        "menu.sync": "Sincronizar tabelas",
        "menu.advanced_sync": "Sincronização avançada",
        "menu.schema": "Estrutura das tabelas",
        "menu.backup": "Backup de tabelas",
        "menu.databases": "Bancos / conexões",
        "menu.logs": "Logs",
        "menu.more": "Mais",
        "menu.exit": "Sair",
        "menu.more.title": "Mais opções",
        "menu.defaults": "Configurações padrão",
        "menu.doctor": "Doctor / diagnóstico",
        "menu.update": "Atualizar sync-db",
        "menu.client": "Cliente MariaDB gerenciado",
        "menu.language": "Idioma",
        "menu.uninstall": "Desinstalar sync-db",
        "menu.back": "Voltar",
        "menu.language.title": "Idioma",
        "language.pt": "Português (Brasil)",
        "language.en": "English",
        "language.saved": "Idioma salvo: {language}",
        "error": "ERRO",
        "failed": "FALHOU",
        "ok": "OK",
        "cancelled": "Cancelado.",
        "no_changes": "Nenhuma alteração foi feita.",
        "prompt.continue": "Continuar?",
        "prompt.apply_plan": "Digite APLICAR para executar este plano: ",
        "prompt.apply_selected": "Digite APLICAR para executar as operações selecionadas: ",
        "prompt.apply_recreate": "Digite APLICAR para recriar a tabela: ",
        "prompt.keep_backup": "Deseja manter tabela atual como backup? [s/N]",
        "prompt.press_enter": "\nPressione Enter para voltar ao menu...",
        "schema.model": "Modelo de estrutura: [bold]{origin}[/]",
        "schema.target": "Banco que será comparado/alterado: [bold]{destination}[/]",
        "schema.tables": "Tabelas: {tables}",
        "schema.plan": "Plano de estrutura: {table} ({action})",
        "schema.no_changes": "Nenhuma alteração necessária.",
        "schema.final_sql": "SQL FINAL",
        "schema.add": "ADICIONAR",
        "schema.modify": "ALTERAR",
        "schema.move": "REORDENAR",
        "schema.drop": "REMOVER",
        "schema.preserve": "PRESERVAR NO DESTINO",
        "schema.columns": "COLUNAS",
        "schema.indexes": "ÍNDICES",
        "schema.foreign_keys": "CHAVES E FKs",
        "schema.table_options": "OPÇÕES DA TABELA",
        "schema.column": "coluna",
        "schema.index": "índice",
        "schema.foreign_key": "FK",
        "schema.table_option": "opção da tabela",
        "schema.destructive": "Atenção: o plano copy contém remoções no destino.",
        "schema.no_table": "A tabela não existe na {side}.",
        "schema.identical": "Estrutura idêntica.",
        "schema.diff.missing_columns": "Colunas ausentes no destino",
        "schema.diff.changed_columns": "Colunas diferentes",
        "schema.diff.reordered_columns": "Colunas em ordem diferente",
        "schema.diff.extra_columns": "Extras no destino",
        "schema.diff.missing_indexes": "Índices ausentes no destino",
        "schema.diff.changed_indexes": "Índices diferentes",
        "schema.diff.extra_indexes": "Índices extras no destino",
        "schema.diff.missing_foreign_keys": "FKs ausentes no destino",
        "schema.diff.changed_foreign_keys": "FKs diferentes",
        "schema.diff.extra_foreign_keys": "FKs extras no destino",
        "schema.diff.changed_table_options": "Opções da tabela diferentes",
    },
    "en": {
        "app.description": "MySQL/MariaDB table synchronizer",
        "help.version": "Show version and exit",
        "help.config": "Alternative path to config.json",
        "help.language": "Interface language for this run (does not save configuration)",
        "help.schema": "Analyze and synchronize table structure",
        "help.schema.diff": "Show structure differences without changing anything",
        "help.schema.copy": "Copy origin structure; may change and remove extras",
        "help.schema.update": "Update structure while preserving destination extras",
        "help.schema.recreate": "Recreate destination table from origin",
        "help.init": "Create default config in the user directory",
        "help.doctor": "Diagnose configuration, clients, and connections",
        "help.update": "Update sync-db from the main GitHub branch",
        "help.sync": "Synchronize tables",
        "help.backup": "Create table backups in the selected database",
        "help.tables": "List identified tables",
        "help.config_cmd": "Manage configuration",
        "help.db": "Manage registered databases/connections",
        "help.client": "Manage portable MariaDB/MySQL client",
        "help.logs": "Manage logs",
        "help.uninstall": "Show uninstall instructions/shortcut",
        "help.tables_arg": "Tables to synchronize",
        "help.file_arg": "Table .csv/.txt file",
        "help.origin": "Model/source database tag",
        "help.destination": "Database tag to change/compare",
        "help.yes_schema": "Confirm schema plan application",
        "help.verbose": "Show detailed read timings",
        "help.plan": "Show change plan without modifying the database",
        "help.plan_action": "Plan to copy structure or update while preserving extras",
        "help.sql": "Include FINAL SQL block after the plan",
        "help.no_sql": "Hide SQL below each operation",
        "help.sql_only": "Print only plan SQL",
        "help.save": "Save documented, executable plan to a SQL file",
        "menu.main": "sync-db menu",
        "menu.sync": "Synchronize tables",
        "menu.advanced_sync": "Advanced synchronization",
        "menu.schema": "Table structure",
        "menu.backup": "Table backup",
        "menu.databases": "Databases / connections",
        "menu.logs": "Logs",
        "menu.more": "More",
        "menu.exit": "Exit",
        "menu.more.title": "More options",
        "menu.defaults": "Default settings",
        "menu.doctor": "Doctor / diagnostics",
        "menu.update": "Update sync-db",
        "menu.client": "Managed MariaDB client",
        "menu.language": "Language",
        "menu.uninstall": "Uninstall sync-db",
        "menu.back": "Back",
        "menu.language.title": "Language",
        "language.pt": "Português (Brasil)",
        "language.en": "English",
        "language.saved": "Language saved: {language}",
        "error": "ERROR",
        "failed": "FAILED",
        "ok": "OK",
        "cancelled": "Cancelled.",
        "no_changes": "No changes were made.",
        "prompt.continue": "Continue?",
        "prompt.apply_plan": "Type APPLY to execute this plan: ",
        "prompt.apply_selected": "Type APPLY to execute the selected operations: ",
        "prompt.apply_recreate": "Type APPLY to recreate the table: ",
        "prompt.keep_backup": "Keep the current table as a backup? [y/N]",
        "prompt.press_enter": "\nPress Enter to return to the menu...",
        "schema.model": "Structure model: [bold]{origin}[/]",
        "schema.target": "Database to compare/change: [bold]{destination}[/]",
        "schema.tables": "Tables: {tables}",
        "schema.plan": "Schema plan: {table} ({action})",
        "schema.no_changes": "No changes required.",
        "schema.final_sql": "FINAL SQL",
        "schema.add": "ADD",
        "schema.modify": "CHANGE",
        "schema.move": "REORDER",
        "schema.drop": "REMOVE",
        "schema.preserve": "PRESERVE IN DESTINATION",
        "schema.columns": "COLUMNS",
        "schema.indexes": "INDEXES",
        "schema.foreign_keys": "KEYS AND FKs",
        "schema.table_options": "TABLE OPTIONS",
        "schema.column": "column",
        "schema.index": "index",
        "schema.foreign_key": "FK",
        "schema.table_option": "table option",
        "schema.destructive": "Warning: the copy plan removes items from the destination.",
        "schema.no_table": "The table does not exist in the {side}.",
        "schema.identical": "Structure is identical.",
        "schema.diff.missing_columns": "Columns missing in destination",
        "schema.diff.changed_columns": "Different columns",
        "schema.diff.reordered_columns": "Columns in a different order",
        "schema.diff.extra_columns": "Extras in destination",
        "schema.diff.missing_indexes": "Indexes missing in destination",
        "schema.diff.changed_indexes": "Different indexes",
        "schema.diff.extra_indexes": "Extra indexes in destination",
        "schema.diff.missing_foreign_keys": "FKs missing in destination",
        "schema.diff.changed_foreign_keys": "Different FKs",
        "schema.diff.extra_foreign_keys": "Extra FKs in destination",
        "schema.diff.changed_table_options": "Different table options",
    },
}

# Parser and interactive-flow text stays in the catalog so language selection
# never leaks conditional branches into command handlers.
CATALOG["pt-BR"].update({
    "help.quiet": "Não imprime mensagens informativas", "help.sync_origin": "Tag do banco de origem", "help.sync_destination": "Tag do banco de destino", "help.last": "Usa as últimas tabelas sincronizadas", "help.mode": "Motor de sincronização", "help.where": "Condição WHERE para sincronização parcial (com ou sem a palavra WHERE)", "help.insert_missing": "Insere apenas linhas da origem cuja chave primária ainda não existe no destino", "help.yes_sync": "Confirma avisos da sincronização avançada", "help.dry_run": "Mostra o que seria feito sem alterar o destino", "help.backup_mode": "Cria backup antes de sobrescrever; sem valor remove ao terminar com sucesso, use --backup keep para manter", "help.backup_destination": "Tag do banco onde o backup será criado", "help.yes_backup": "Usa nomes sugeridos sem perguntar", "help.recreate_yes": "Confirma a recriação da tabela", "help.keep_backup": "Mantém a tabela anterior com nome de backup datado", "help.tables_inline": "Tabelas inline", "help.tables_file": "Arquivo .csv/.txt", "help.config.path": "Mostra caminho do config", "help.config.show": "Mostra config com senha mascarada", "help.config.edit": "Abre config no editor padrão", "help.config.remove": "Remove config com confirmação", "help.db.list": "Lista bancos cadastrados", "help.db.add": "Cadastra banco interativamente", "help.db.tag": "Tag do banco", "help.db.edit": "Edita banco interativamente", "help.db.remove": "Remove banco", "help.db.test": "Testa conexão de um banco", "help.db.defaults": "Define origem/destino padrão", "help.client.status": "Mostra clientes disponíveis", "help.client.path": "Mostra pasta do cliente gerenciado", "help.client.install": "Instala cliente gerenciado explicitamente", "help.client.remove": "Remove cliente gerenciado", "help.client.update": "Atualiza cliente gerenciado (alias para install)", "help.logs.path": "Mostra caminho dos logs", "help.logs.tail": "Mostra últimas linhas do log", "help.logs.lines": "Quantidade de linhas", "help.logs.open": "Abre pasta dos logs", "help.logs.clear": "Limpa logs", "help.uninstall.all": "Remove também config, cliente gerenciado e logs", "help.uninstall.keep_config": "Remove app e mantém config", "help.archive_url": "URL opcional de um .zip/.tar.gz customizado com binários mariadb/mariadb-dump", "help.sha256": "SHA256 esperado quando usar --archive-url", "help.yes": "Não pedir confirmação",
    "menu.navigation": "Use ↑/↓ para navegar, Enter para selecionar, Esc/← para voltar. Números também funcionam.", "menu.more_above": "↑ mais opções acima", "menu.more_below": "↓ mais opções abaixo", "menu.back_numbered": "Voltar", "menu.choose": "Escolha: ", "menu.sync.title": "Sincronizando tabelas", "menu.sync.summary": "Resumo da sincronização", "menu.context.origin": "Origem escolhida: {origin}", "menu.context.destination": "Destino escolhido: {destination}", "menu.context.tables": "Tabelas escolhidas: {tables}", "menu.context.mode": "Motor escolhido: {mode}", "menu.step.origin": "Escolha o banco de origem", "menu.step.destination": "Escolha o banco de destino", "menu.step.tables": "Escolha as tabelas que serão sincronizadas", "menu.step.mode": "Escolha o motor", "menu.use_last": "Usar últimas ({tables})", "menu.enter_tables": "Digitar tabelas", "menu.table_prompt": "Tabelas: ", "menu.backup.title": "Backup de tabelas", "menu.backup.choose_destination": "Escolha o banco onde os backups serão criados", "menu.backup.context": "Banco escolhido: {destination}\nDigite as tabelas que serão copiadas para backup.", "menu.backup.names": "Nomes sugeridos dos backups. Pressione Enter para confirmar ou edite o nome.", "menu.backup.name": "Backup para {table}", "menu.manual.review": "Revisar/aplicar selecionadas", "menu.manual.title": "Seleção manual", "menu.manual.footer": "[x] selecionada; [ ] não será aplicada. As operações são agrupadas por ação e categoria.", "menu.manual.none": "Nenhuma operação foi selecionada. Nenhuma alteração foi feita.", "menu.manual.review_title": "Revisão das operações selecionadas", "menu.schema.model": "Modelo: {origin}\nBanco que será alterado: {destination}\nDigite as tabelas para analisar.",
    "menu.no_table": "Nenhuma tabela informada.", "menu.schema.origin": "Estrutura das tabelas — modelo/origem", "menu.schema.destination": "Estrutura das tabelas — banco que será alterado", "menu.schema.diff": "Ver diferenças", "menu.schema.copy": "Copiar estrutura", "menu.schema.copy_description": "deixa o destino igual à origem; pode alterar e remover extras", "menu.schema.update": "Atualizar preservando extras", "menu.schema.update_description": "copia a estrutura da origem, mas não remove extras do destino", "menu.schema.manual": "Escolher manualmente o que aplicar", "menu.schema.manual_description": "modo interativo: escolha colunas, índices e chaves após ver o diff", "menu.schema.recreate": "Recriar tabela a partir da origem", "menu.schema.recreate_description": "backup opcional", "menu.schema.main": "Voltar ao menu principal", "menu.schema.reselect": "Pressione T para escolher as tabelas novamente", "menu.schema.warning": "ATENÇÃO: este modo recria a tabela no destino. Backup é opcional e deve ser feito separadamente se desejado.", "prompt.apply_choice": "Aplicar plano? [a]plicar/[v]oltar: ", "prompt.cancelled_no_changes": "Cancelado. Nenhuma alteração foi feita.", "prompt.apply_word": "APLICAR", "prompt.confirm": "Continuar?", "prompt.where": "Digite a condição WHERE: ", "prompt.press_enter": "\nPressione Enter para voltar ao menu...",
})

CATALOG["en"].update({
    "help.quiet": "Do not print informational messages", "help.sync_origin": "Source database tag", "help.sync_destination": "Destination database tag", "help.last": "Use the most recently synchronized tables", "help.mode": "Synchronization engine", "help.where": "WHERE condition for partial synchronization (with or without the WHERE keyword)", "help.insert_missing": "Insert only source rows whose primary key does not yet exist in destination", "help.yes_sync": "Confirm advanced synchronization warnings", "help.dry_run": "Show what would be done without changing destination", "help.backup_mode": "Create a backup before overwriting; without a value it is removed after success, use --backup keep to retain it", "help.backup_destination": "Database tag where the backup will be created", "help.yes_backup": "Use suggested names without asking", "help.recreate_yes": "Confirm table recreation", "help.keep_backup": "Keep the previous table with a dated backup name", "help.tables_inline": "Inline tables", "help.tables_file": ".csv/.txt file", "help.config.path": "Show config path", "help.config.show": "Show config with password masked", "help.config.edit": "Open config in the default editor", "help.config.remove": "Remove config with confirmation", "help.db.list": "List registered databases", "help.db.add": "Register a database interactively", "help.db.tag": "Database tag", "help.db.edit": "Edit a database interactively", "help.db.remove": "Remove database", "help.db.test": "Test a database connection", "help.db.defaults": "Set default source/destination", "help.client.status": "Show available clients", "help.client.path": "Show managed-client folder", "help.client.install": "Install managed client explicitly", "help.client.remove": "Remove managed client", "help.client.update": "Update managed client (alias for install)", "help.logs.path": "Show log path", "help.logs.tail": "Show latest log lines", "help.logs.lines": "Number of lines", "help.logs.open": "Open logs folder", "help.logs.clear": "Clear logs", "help.uninstall.all": "Also remove config, managed client, and logs", "help.uninstall.keep_config": "Remove app and keep config", "help.archive_url": "Optional URL for a custom .zip/.tar.gz containing mariadb/mariadb-dump binaries", "help.sha256": "Expected SHA256 when using --archive-url", "help.yes": "Do not ask for confirmation",
    "menu.navigation": "Use ↑/↓ to navigate, Enter to select, Esc/← to go back. Numbers also work.", "menu.more_above": "↑ more options above", "menu.more_below": "↓ more options below", "menu.back_numbered": "Back", "menu.choose": "Choose: ", "menu.sync.title": "Synchronizing tables", "menu.sync.summary": "Synchronization summary", "menu.context.origin": "Selected source: {origin}", "menu.context.destination": "Selected destination: {destination}", "menu.context.tables": "Selected tables: {tables}", "menu.context.mode": "Selected engine: {mode}", "menu.step.origin": "Choose the source database", "menu.step.destination": "Choose the destination database", "menu.step.tables": "Choose tables to synchronize", "menu.step.mode": "Choose the engine", "menu.use_last": "Use latest ({tables})", "menu.enter_tables": "Enter tables", "menu.table_prompt": "Tables: ", "menu.backup.title": "Table backup", "menu.backup.choose_destination": "Choose the database where backups will be created", "menu.backup.context": "Selected database: {destination}\nEnter tables to copy as backups.", "menu.backup.names": "Suggested backup names. Press Enter to confirm or edit the name.", "menu.backup.name": "Backup for {table}", "menu.manual.review": "Review/apply selected", "menu.manual.title": "Manual selection", "menu.manual.footer": "[x] selected; [ ] will not be applied. Operations are grouped by action and category.", "menu.manual.none": "No operations were selected. No changes were made.", "menu.manual.review_title": "Review selected operations", "menu.schema.model": "Model: {origin}\nDatabase to change: {destination}\nEnter tables to analyze.",
    "menu.no_table": "No table was provided.", "menu.schema.origin": "Table structure — model/source", "menu.schema.destination": "Table structure — database to change", "menu.schema.diff": "View differences", "menu.schema.copy": "Copy structure", "menu.schema.copy_description": "makes destination match origin; may change and remove extras", "menu.schema.update": "Update while preserving extras", "menu.schema.update_description": "copies origin structure without removing destination extras", "menu.schema.manual": "Choose what to apply manually", "menu.schema.manual_description": "interactive mode: choose columns, indexes, and keys after viewing the diff", "menu.schema.recreate": "Recreate table from origin", "menu.schema.recreate_description": "optional backup", "menu.schema.main": "Back to main menu", "menu.schema.reselect": "Press T to choose tables again", "menu.schema.warning": "WARNING: this mode recreates the destination table. Backup is optional and should be created separately if desired.", "prompt.apply_choice": "Apply plan? [a]pply/[b]ack: ", "prompt.cancelled_no_changes": "Cancelled. No changes were made.", "prompt.apply_word": "APPLY", "prompt.confirm": "Continue?", "prompt.where": "Enter the WHERE condition: ", "prompt.press_enter": "\nPress Enter to return to the menu...",
})

CATALOG["pt-BR"].update({
    "schema.origin": "origem", "schema.destination": "destino",
    "prompt.yes_no": "s/N",
    "sync.flow": "Fluxo: {origin} → {destination}", "sync.engine": "Motor: {engine} — {reason}",
    "doctor.clients.title": "Clientes / motores", "status.item": "Item", "status.details": "Detalhes",
    "status.managed_client": "Cliente gerenciado", "status.system_client": "Cliente do sistema", "status.python_engine": "Engine Python", "status.recommended_engine": "Motor recomendado",
    "status.not_installed": "não instalado", "status.not_found": "não encontrado", "status.not_found_path": "não encontrado no PATH", "status.available": "disponível", "status.install_command": "não instalado — rode: sync-db client install", "status.incomplete_connection": "host/user/database ainda não configurados",
    "client.reason.python": "Modo python solicitado.", "client.reason.available": "Cliente {source} disponível ({vendor}).", "client.reason.dump_missing": "Modo dump solicitado, mas nenhum cliente dump está instalado.", "client.reason.fallback": "Nenhum cliente dump disponível; usando engine Python.",
    "doctor.connections.title": "Conexões", "doctor.name": "Nome", "doctor.version_message": "Versão / mensagem", "doctor.no_databases": "Nenhum banco cadastrado. Rode: sync-db db add",
    "client.title": "Cliente MariaDB / MySQL", "client.managed_folder": "Pasta gerenciada",
    "backup.result.title": "Backups", "backup.table": "Backup",
    "advanced.source": "Banco de origem", "advanced.destination": "Banco de destino", "advanced.tables": "Escolher tabelas", "advanced.where": "Adicionar condicional (WHERE)", "advanced.rows": "Quais linhas adicionar", "advanced.engine": "Motor de sincronização", "advanced.run": "Executar sincronização avançada", "advanced.none": "não", "advanced.not_selected": "não escolhido", "advanced.rows.all": "TODAS — substitui a tabela inteira", "advanced.rows.where": "TODAS — substitui as linhas encontradas pelo WHERE", "advanced.rows.missing": "apenas novas da origem — mantém linhas existentes no destino e insere só PKs faltantes", "advanced.backup.none": "não cria backup antes de sincronizar", "advanced.backup.temp": "sim, temporário", "advanced.backup.temp_description": "remove o backup se a sincronização concluir com sucesso", "advanced.backup.keep": "sim, manter", "advanced.backup.keep_description": "mantém o backup no banco após sincronizar com sucesso", "advanced.mode.required": "obrigatório para WHERE/insert-missing nesta versão", "advanced.mode.recommended": "recomendado", "advanced.mode.managed": "MariaDB gerenciado", "advanced.mode.system": "cliente do sistema", "advanced.mode.python": "fallback sem dump", "advanced.title": "Sincronização avançada", "advanced.origin.title": "Sincronização avançada — origem", "advanced.destination.title": "Sincronização avançada — destino", "advanced.run.summary": "Resumo da sincronização avançada", "advanced.where.prompt": "Digite a condição WHERE: ", "advanced.run.missing": "escolha origem, destino e tabelas antes de executar.", "advanced.rows.all_description": "substitui a tabela inteira ou as linhas encontradas pelo WHERE", "advanced.rows.missing_description": "mantém existentes e insere só PKs faltantes",
    "db.edit": "Banco para editar", "db.test": "Banco para testar", "db.remove": "Banco para remover", "db.list": "Listar bancos", "db.add": "Adicionar banco", "db.edit_action": "Editar banco", "db.test_action": "Testar banco", "db.remove_action": "Remover banco",
    "logs.path": "Mostrar caminho", "logs.tail": "Ver últimas linhas", "logs.open": "Abrir pasta", "logs.clear": "Limpar logs",
    "client.status": "Status", "client.install": "Instalar/atualizar MariaDB", "client.remove": "Remover MariaDB", "advanced.rows.all_label": "TODAS", "advanced.rows.missing_label": "apenas novas da origem",
})
CATALOG["en"].update({
    "schema.origin": "source", "schema.destination": "destination",
    "prompt.yes_no": "y/N",
    "sync.flow": "Flow: {origin} → {destination}", "sync.engine": "Engine: {engine} — {reason}",
    "doctor.clients.title": "Clients / engines", "status.item": "Item", "status.details": "Details",
    "status.managed_client": "Managed client", "status.system_client": "System client", "status.python_engine": "Python engine", "status.recommended_engine": "Recommended engine",
    "status.not_installed": "not installed", "status.not_found": "not found", "status.not_found_path": "not found on PATH", "status.available": "available", "status.install_command": "not installed — run: sync-db client install", "status.incomplete_connection": "host/user/database are not configured yet",
    "client.reason.python": "Python mode requested.", "client.reason.available": "{source} client available ({vendor}).", "client.reason.dump_missing": "Dump mode requested, but no dump client is installed.", "client.reason.fallback": "No dump client is available; using the Python engine.",
    "doctor.connections.title": "Connections", "doctor.name": "Name", "doctor.version_message": "Version / message", "doctor.no_databases": "No database is registered. Run: sync-db db add",
    "client.title": "MariaDB / MySQL client", "client.managed_folder": "Managed folder",
    "backup.result.title": "Backups", "backup.table": "Backup",
    "advanced.source": "Source database", "advanced.destination": "Destination database", "advanced.tables": "Choose tables", "advanced.where": "Add condition (WHERE)", "advanced.rows": "Which rows to add", "advanced.engine": "Synchronization engine", "advanced.run": "Run advanced synchronization", "advanced.none": "none", "advanced.not_selected": "not selected", "advanced.rows.all": "ALL — replaces the entire table", "advanced.rows.where": "ALL — replaces rows matched by WHERE", "advanced.rows.missing": "only new rows from source — keeps existing destination rows and inserts only missing primary keys", "advanced.backup.none": "do not create a backup before synchronizing", "advanced.backup.temp": "yes, temporary", "advanced.backup.temp_description": "removes the backup after synchronization succeeds", "advanced.backup.keep": "yes, keep", "advanced.backup.keep_description": "keeps the backup in the database after synchronization succeeds", "advanced.mode.required": "required for WHERE/insert-missing in this version", "advanced.mode.recommended": "recommended", "advanced.mode.managed": "Managed MariaDB", "advanced.mode.system": "system client", "advanced.mode.python": "fallback without dump", "advanced.title": "Advanced synchronization", "advanced.origin.title": "Advanced synchronization — source", "advanced.destination.title": "Advanced synchronization — destination", "advanced.run.summary": "Advanced synchronization summary", "advanced.where.prompt": "Enter the WHERE condition: ", "advanced.run.missing": "choose source, destination, and tables before running.", "advanced.rows.all_description": "replaces the entire table or rows matched by WHERE", "advanced.rows.missing_description": "keeps existing rows and inserts only missing primary keys",
    "db.edit": "Database to edit", "db.test": "Database to test", "db.remove": "Database to remove", "db.list": "List databases", "db.add": "Add database", "db.edit_action": "Edit database", "db.test_action": "Test database", "db.remove_action": "Remove database",
    "logs.path": "Show path", "logs.tail": "View latest lines", "logs.open": "Open folder", "logs.clear": "Clear logs",
    "client.status": "Status", "client.install": "Install/update MariaDB", "client.remove": "Remove MariaDB", "advanced.rows.all_label": "ALL", "advanced.rows.missing_label": "only new rows from source",
})


def normalize_language(value: object) -> str:
    if isinstance(value, str) and value.lower() in {"pt", "pt-br", "pt_br"}:
        return "pt-BR"
    if isinstance(value, str) and value.lower() in {"en", "en-us", "en_us"}:
        return "en"
    return DEFAULT_LANGUAGE


def set_language(language: object) -> str:
    normalized = normalize_language(language)
    _current_language.set(normalized)
    return normalized


def get_language() -> str:
    return _current_language.get()


def t(key: str, /, **params: object) -> str:
    language = get_language()
    value = CATALOG.get(language, CATALOG[DEFAULT_LANGUAGE]).get(key)
    if value is None:
        value = CATALOG[DEFAULT_LANGUAGE].get(key, key)
    return value.format(**params)
