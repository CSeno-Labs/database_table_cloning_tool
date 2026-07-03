param(
    [switch]$All
)

$ErrorActionPreference = "Continue"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool uninstall database-table-cloning-tool
} elseif (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx uninstall database-table-cloning-tool
} else {
    Write-Host "uv/pipx não encontrados. Se o comando sync-db ainda existir, remova-o manualmente do PATH."
}

if ($All) {
    Remove-Item -Recurse -Force "$env:APPDATA\sync-db" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$env:LOCALAPPDATA\sync-db" -ErrorAction SilentlyContinue
    Write-Host "Programa e dados removidos."
} else {
    Write-Host "Programa removido. Config/dados foram mantidos. Use -All para remover tudo."
}
