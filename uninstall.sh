#!/usr/bin/env sh
set -eu

REMOVE_ALL="0"
for arg in "$@"; do
  case "$arg" in
    --all) REMOVE_ALL="1" ;;
    -h|--help)
      echo "Usage: ./uninstall.sh [--all]"
      exit 0
      ;;
  esac
done

if command -v uv >/dev/null 2>&1; then
  uv tool uninstall database-table-cloning-tool || true
elif command -v pipx >/dev/null 2>&1; then
  pipx uninstall database-table-cloning-tool || true
else
  echo "uv/pipx não encontrados. Se o comando sync-db ainda existir, remova-o manualmente do PATH."
fi

if [ "$REMOVE_ALL" = "1" ]; then
  rm -rf "$HOME/.config/sync-db" "$HOME/.local/share/sync-db" "$HOME/.local/state/sync-db" "$HOME/.cache/sync-db"
  rm -rf "$HOME/Library/Application Support/sync-db" "$HOME/Library/Logs/sync-db" 2>/dev/null || true
  echo "Programa e dados removidos."
else
  echo "Programa removido. Config/dados foram mantidos. Use --all para remover tudo."
fi
