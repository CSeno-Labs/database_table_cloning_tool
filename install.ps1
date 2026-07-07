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

$UserBin = Join-Path $env:USERPROFILE ".local\bin"
$OldAlias = Join-Path $UserBin "sinc-db.exe"
if (Test-Path $OldAlias) {
    Remove-Item $OldAlias -Force
}
$SyncDbExe = Join-Path $UserBin "sync-db.exe"
$env:Path = "$UserBin;$env:Path"

& $SyncDbExe init --quiet

$installClient = $false
if ($WithClient) {
    $installClient = $true
} elseif (-not $NoClient) {
    $ans = Read-Host "Deseja instalar agora o cliente MariaDB portátil gerenciado? [s/N]"
    $installClient = $ans -match '^(s|sim|y|yes)$'
}

if ($installClient) {
    Write-Host "Instalando cliente MariaDB portátil gerenciado..."
    & $SyncDbExe client install --yes
}
