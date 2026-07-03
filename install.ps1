param(
    [switch]$WithClient,
    [switch]$NoClient,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/CSeno-Labs/database_table_cloning_tool.git"

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { return }
    Write-Host "uv não encontrado. Instalando uv..."
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Ensure-Uv

$hasPyproject = Test-Path "pyproject.toml"
if ($Dev) {
    if (-not $hasPyproject) {
        throw "-Dev precisa ser executado dentro do repositório clonado."
    }
    uv tool install --reinstall --editable .
} else {
    if ($hasPyproject) {
        uv tool install --reinstall .
    } else {
        uv tool install --reinstall "git+$RepoUrl"
    }
}

sync-db init
Write-Host ""
Write-Host "sync-db instalado. Rode: sync-db doctor"
Write-Host ""

$installClient = $false
if ($WithClient) {
    $installClient = $true
} elseif (-not $NoClient) {
    $ans = Read-Host "Deseja instalar agora o cliente MariaDB portátil gerenciado? [s/N]"
    $installClient = $ans -match '^(s|sim|y|yes)$'
}

if ($installClient) {
    Write-Host "A instalação do cliente gerenciado é explícita e nunca acontece durante sync."
    Write-Host "Nesta branch inicial, rode com uma URL oficial/validada quando definida:"
    Write-Host "  sync-db client install --archive-url <url-do-pacote-mariadb-portatil>"
} else {
    Write-Host "Cliente gerenciado não instalado. O sync tentará cliente do sistema e fallback Python."
}
