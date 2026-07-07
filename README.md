# sync-db

CLI para sincronizar tabelas MySQL/MariaDB entre ambientes, com foco em instalação simples e diagnóstico claro.

Status desta branch: reestruturação inicial para CLI instalável. A GUI antiga ainda não é foco.

## Objetivo

Permitir que qualquer colega instale o programa e rode:

```bash
sync-db
sync-db doctor
sync-db sync -t periodo aluno escola -o prod -d local
```

sem depender de caminho hardcoded do XAMPP, `.bat` local, Docker ou MySQL Client instalado. Rodar apenas `sync-db` abre o menu interativo; não dispara sincronização automaticamente.

## Motores de sincronização

O `sync-db sync` nunca baixa nem instala binários escondido.

No modo padrão (`auto`), ele usa o que já estiver disponível, nesta ordem:

1. Cliente gerenciado pelo próprio `sync-db` (`mariadb`/`mariadb-dump`) instalado previamente pelo instalador ou por `sync-db client install`.
2. Cliente MariaDB/MySQL encontrado no sistema (`mariadb-dump`, `mariadb`, `mysqldump`, `mysql`).
3. Engine Python usando `mysql-connector-python`.

Se o usuário forçar `--mode dump`, `--mode managed-dump` ou `--mode system-dump` e nenhum cliente compatível existir, o programa erra com instruções claras.

## Instalação em uma linha

Linux/macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/CSeno-Labs/database_table_cloning_tool/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CSeno-Labs/database_table_cloning_tool/main/install.ps1 | iex"
```

O instalador pergunta se deve instalar o cliente MariaDB gerenciado. Para automatizar:

```powershell
.\install.ps1 -WithClient
```

ou:

```powershell
.\install.ps1 -NoClient
```

## Instalação a partir do repositório clonado

```bash
git clone https://github.com/CSeno-Labs/database_table_cloning_tool.git
cd database_table_cloning_tool
./install.sh
```

Windows:

```powershell
git clone https://github.com/CSeno-Labs/database_table_cloning_tool.git
cd database_table_cloning_tool
.\install.ps1
```

Modo desenvolvimento/editável:

```bash
./install.sh --dev
```

```powershell
.\install.ps1 -Dev
```

## Comandos principais

Criar config padrão:

```bash
sync-db init
```

Diagnosticar ambiente:

```bash
sync-db doctor
```

Sincronizar tabelas:

```bash
sync-db sync -t periodo aluno escola
sync-db sync -t periodo -o prod -d local
sync-db sync -t aluno --where "ano >= 2026"
sync-db sync -t aluno --insert-missing
sync-db sync -t aluno --insert-missing --where "ano >= 2026"
sync-db sync -t aluno --where "ano >= 2026" --dry-run
sync-db sync -t aluno --where "ano >= 2026" --backup keep
sync-db sync -t escola aluno --where "idescola = 123" -y
sync-db sync -t periodo -o prod -d local --backup        # backup temporário: remove se concluir com sucesso
sync-db sync -t periodo -o prod -d local --backup temp   # igual a --backup
sync-db sync -t periodo -o prod -d local --backup keep   # mantém backup no banco
sync-db backup -t periodo aluno -d local -y
sync-db --version
```

A forma curta também funciona:

```bash
sync-db -t periodo -o prod -d local
```

Rodar só `sync-db` abre o menu interativo com setas:

```text
1 - Sincronizar tabelas
2 - Sincronização avançada
3 - Backup de tabelas
4 - Bancos / conexões
5 - Logs
6 - Mais
7 - Sair
```

Use ↑/↓ para navegar, Enter para selecionar e Esc/← para voltar.

Na sincronização simples pelo menu, quando o backup é ativado ele é sempre temporário: o backup é removido automaticamente se a sincronização terminar com sucesso. Para manter backup no banco, use `--backup keep` no comando ou a opção de backup da Sincronização avançada.

Sincronizar por arquivo:

```bash
sync-db sync -f tabelas_puxar.csv
```

Forçar engine Python:

```bash
sync-db sync -t periodo --mode python
```

Forçar dump:

```bash
sync-db sync -t periodo --mode dump
sync-db sync -t periodo --mode managed-dump
sync-db sync -t periodo --mode system-dump
```

## Configuração

O config fica na pasta do usuário, não dentro do repositório. Ele suporta vários bancos cadastrados no mesmo arquivo.

Ver caminho:

```bash
sync-db config path
```

Mostrar config com senha mascarada:

```bash
sync-db config show
```

Editar:

```bash
sync-db config edit
```

Formato base:

```json
{
  "profiles": {
    "prod": {
      "label": "Produção leitura",
      "host": "host-da-origem",
      "port": 3306,
      "user": "usuario",
      "password": "senha",
      "database": "banco_origem",
      "charset": "latin1",
      "allow_as_origin": true,
      "allow_as_destination": false
    },
    "local": {
      "label": "Local",
      "host": "127.0.0.1",
      "port": 3306,
      "user": "root",
      "password": "",
      "database": "banco_destino",
      "charset": "latin1",
      "allow_as_origin": true,
      "allow_as_destination": true
    }
  },
  "defaults": {
    "origin": "prod",
    "destination": "local"
  },
  "sync": {
    "last_tables_file": "last_tables.txt",
    "truncate_before_insert": true,
    "create_missing_tables": true,
    "add_missing_columns": true,
    "batch_size": 1000
  },
  "client": {
    "mode": "auto",
    "preferred_source": "managed",
    "vendor": "mariadb"
  }
}
```

Comandos para bancos:

```bash
sync-db db list
sync-db db add
sync-db db edit prod
sync-db db remove homolog
sync-db db test prod
sync-db db set-defaults -o prod -d local
```

`allow_as_destination=false` marca um banco como somente origem/source_only, útil para produção de leitura.

O arquivo `last_tables.txt` guarda as últimas tabelas sincronizadas. Ele não é usado automaticamente por `sync-db` sem flags; para reutilizar explicitamente:

```bash
sync-db sync --last
```

Não existe `auto_download`: instalação de cliente é sempre explícita.

## Cliente gerenciado

Comandos:

```bash
sync-db client status
sync-db client path
sync-db client install
sync-db client remove
sync-db client update
```

`sync-db client install` detecta o sistema/arquitetura e baixa um pacote oficial MariaDB via API de downloads do MariaDB. A instalação é explícita: o comando mostra pacote, destino e SHA256 antes de instalar, e o `sync-db sync` nunca baixa nada escondido.

Plataformas automáticas suportadas nesta versão:

- Windows x64: pacote `mariadb-*-winx64.zip`
- Linux x86_64: pacote `mariadb-*-linux-systemd-x86_64.tar.gz`

Uso recomendado:

```bash
sync-db client install
```

Sem confirmação interativa:

```bash
sync-db client install --yes
```

Pacote customizado ainda é possível:

```bash
sync-db client install --archive-url https://exemplo/pacote-mariadb-portatil.zip --sha256 <sha256>
```

## Docker

O programa não precisa saber que o banco está em Docker se a porta estiver exposta.

Exemplo:

```yaml
services:
  mysql:
    image: mysql:8
    ports:
      - "3306:3306"
```

Config destino:

```json
{
  "host": "127.0.0.1",
  "port": 3306,
  "user": "root",
  "password": "root",
  "database": "app"
}
```

Se a porta não estiver exposta, nenhum cliente externo consegue conectar sem usar Docker diretamente.

## Desinstalação

Linux/macOS:

```bash
./uninstall.sh
```

Remover também config/dados:

```bash
./uninstall.sh --all
```

Windows:

```powershell
.\uninstall.ps1
```

Remover também config/dados:

```powershell
.\uninstall.ps1 -All
```

Ou pelo próprio comando:

```bash
sync-db uninstall
```

## Desenvolvimento

Rodar testes:

```bash
uv run --with pytest --with platformdirs --with rich --with mysql-connector-python pytest tests -q
```

Rodar CLI local:

```bash
uv run sync-db --help
```
