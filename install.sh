#!/usr/bin/env sh
set -eu

REPO_URL="https://github.com/CSeno-Labs/database_table_cloning_tool.git"
WITH_CLIENT="ask"
DEV="0"

for arg in "$@"; do
  case "$arg" in
    --with-client) WITH_CLIENT="yes" ;;
    --no-client) WITH_CLIENT="no" ;;
    --dev) DEV="1" ;;
    -h|--help)
      cat <<'HELP'
Usage: ./install.sh [--with-client|--no-client] [--dev]

Instala o comando sync-db.
- Sem --dev: instala a versão do diretório atual se houver pyproject.toml, senão do GitHub.
- Com --dev: instala o checkout atual em modo editável.
- --with-client: instala cliente gerenciado explicitamente quando a URL oficial estiver configurada.
HELP
      exit 0
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  echo "uv não encontrado. Instalando uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ -f "pyproject.toml" ]; then
  TARGET="."
else
  TARGET="git+$REPO_URL"
fi

if [ "$DEV" = "1" ]; then
  if [ ! -f "pyproject.toml" ]; then
    echo "--dev precisa ser executado dentro do repositório clonado." >&2
    exit 2
  fi
  uv tool install --reinstall --editable .
else
  uv tool install --reinstall "$TARGET"
fi

SYNC_DB_BIN="$HOME/.local/bin/sync-db"
rm -f "$HOME/.local/bin/sinc-db" "$HOME/.local/bin/sinc-db.exe"
if [ -x "$SYNC_DB_BIN" ]; then
  "$SYNC_DB_BIN" init
else
  sync-db init
fi

echo ""
echo "sync-db instalado. Rode: sync-db doctor"
echo ""

if [ "$WITH_CLIENT" = "ask" ]; then
  printf "Deseja instalar agora o cliente MariaDB portátil gerenciado? [s/N] "
  read ans || ans=""
  case "$ans" in s|S|sim|SIM|y|Y|yes|YES) WITH_CLIENT="yes" ;; *) WITH_CLIENT="no" ;; esac
fi

if [ "$WITH_CLIENT" = "yes" ]; then
  echo "Instalando cliente MariaDB portátil gerenciado..."
  if [ -x "$SYNC_DB_BIN" ]; then
    "$SYNC_DB_BIN" client install --yes
  else
    sync-db client install --yes
  fi
else
  echo "Cliente gerenciado não instalado. O sync tentará cliente do sistema e fallback Python."
fi
