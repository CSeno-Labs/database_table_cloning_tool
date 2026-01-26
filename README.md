# sync-db 🚀

**English** | [Português](#português)

A professional CLI tool to synchronize specific MySQL tables between different environments (e.g., Production RDS to Localhost) with structure detection and progress visualization.

## ✨ Key Features

- **Smart Sync**: Automatically creates missing tables or adds new columns to existing ones.
- **Visual Progress**: Real-time progress bars and status panels via `rich`.
- **Memory Efficient**: Streams large data in chunks to save RAM.
- **Global Access**: Command-line support to run from any directory.
- **Centralized Config**: Manage credentials and aliases in a single `config.json`.

## 🚀 Quick Start

1. **Install dependencies**:
   ```bash
   pip install mysql-connector-python rich
   ```
2. **Configure `config.json`** with your source (`origem`) and destination (`destino`) credentials.
3. **Run**:
   ```bash
   python sync-db.py
   ```

## 🛠️ CLI Arguments

- `-t, --tables`: Sync specific tables (e.g., `-t user logs`).
- `-f, --file`: Sync tables from a custom TXT/CSV file.
- `-s, --showtables`: List identified tables without syncing (Dry run).
- `-l, --logs`: Show the last 20 log entries.

## 💻 Global Installation (Windows)

To use `sinc-db` from any folder:
1. Add the project folder path to your System **Environment Variables** (PATH).
2. Open a new terminal and type:
   ```bash
   sinc-db -t table_name
   ```

---

## Português

Ferramenta CLI para sincronização inteligente de tabelas MySQL entre ambientes (ex: Produção para Local), com detecção de estrutura e progresso visual.

## ✨ Funcionalidades

- **Sincronização Inteligente**: Cria tabelas ausentes ou adiciona novas colunas automaticamente.
- **Progresso Visual**: Barras de progresso e painéis coloridos via `rich`.
- **Eficiência**: Processa grandes volumes de dados em pedaços (chunks).
- **Acesso Global**: Suporte para execução via terminal em qualquer diretório.
- **Configuração Central**: Credenciais e apelidos gerenciados no `config.json`.

## 🚀 Início Rápido

1. **Instale as dependências**:
   ```bash
   pip install mysql-connector-python rich
   ```
2. **Configure o `config.json`** com as credenciais de `origem` e `destino`.
3. **Execute**:
   ```bash
   python sync-db.py
   ```

## 🛠️ Argumentos CLI

- `-t, --tables`: Sincroniza tabelas específicas (ex: `-t usuario logs`).
- `-f, --file`: Sincroniza tabelas de um arquivo TXT/CSV personalizado.
- `-s, --showtables`: Apenas lista as tabelas (sem sincronizar).
- `-l, --logs`: Exibe as últimas 20 entradas de log.

## 💻 Instalação Global (Windows)

Para usar o comando `sinc-db` em qualquer pasta:
1. Adicione o caminho da pasta do projeto às **Variáveis de Ambiente** (PATH) do Sistema.
2. Abra um novo terminal e digite:
   ```bash
   sinc-db -t nome_da_tabela
   ```