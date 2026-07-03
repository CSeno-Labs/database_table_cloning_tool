# sync-db

CLI para sincronizar tabelas MySQL/MariaDB entre ambientes, com foco em instalação simples e diagnóstico claro.

Status desta branch: reestruturação inicial para CLI instalável. A GUI antiga ainda não é foco.

## Objetivo

Permitir que qualquer colega instale o programa e rode:

```bash
sync-db doctor
sync-db sync -t periodo aluno escola
```

sem depender de caminho hardcoded do XAMPP, `.bat` local, Docker ou MySQL Client instalado.

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
```

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

O config fica na pasta do usuário, não dentro do repositório.

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
  "origem": {
    "alias": "PROD",
    "host": "host-da-origem",
    "port": 3306,
    "user": "usuario",
    "password": "senha",
    "database": "banco_origem",
    "charset": "latin1"
  },
  "destino": {
    "alias": "LOCAL",
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "banco_destino",
    "charset": "latin1"
  },
  "sync": {
    "default_tables_file": "tabelas_puxar.csv",
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
