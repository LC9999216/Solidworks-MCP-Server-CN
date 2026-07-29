# SolidWorks MCP Server — Windows installer
#
# Installs everything needed to use the SolidWorks MCP server with Claude
# Desktop, with no prerequisites (no Python, no git required):
#
#   1. Installs uv (a fast Python manager) if it isn't already installed
#   2. Downloads the latest release of this project from GitHub
#   3. Creates an isolated Python environment and installs dependencies
#   4. Registers the server in Claude Desktop's config (backing it up first)
#
# Usage (paste into PowerShell):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/HarrierPigeon/Solidworks-MCP-Server/main/scripts/install.ps1 | iex"
#
# Re-running the script updates an existing install in place.
# To uninstall: delete  %LOCALAPPDATA%\SolidWorksMCP  and remove the
# "solidworks" entry from claude_desktop_config.json.

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo       = 'HarrierPigeon/Solidworks-MCP-Server'
$InstallDir = Join-Path $env:LOCALAPPDATA 'SolidWorksMCP'
$AppDir     = Join-Path $InstallDir 'app'
$VenvDir    = Join-Path $InstallDir 'venv'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }

Write-Host ''
Write-Host 'SolidWorks MCP Server installer' -ForegroundColor White
Write-Host '-------------------------------'

# --- 1. Ensure uv ----------------------------------------------------------
Write-Step 'Checking for uv...'
$uv = $null
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) { $uv = $uvCmd.Source }
if (-not $uv) {
    Write-Step 'Installing uv (Python environment manager)...'
    try {
        winget install --id=astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
    } catch {}
    # Probe the places uv lands (PATH updates don't reach this session)
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
    )
    foreach ($c in $candidates) { if (-not $uv -and (Test-Path $c)) { $uv = $c } }
    if (-not $uv) {
        # winget unavailable or failed — use Astral's official installer
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $c = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        if (Test-Path $c) { $uv = $c }
    }
    if (-not $uv) { throw 'Could not install uv. Install it manually from https://docs.astral.sh/uv/ and re-run.' }
}
Write-Ok "uv: $uv"

# --- 2. Download the server ------------------------------------------------
Write-Step 'Downloading SolidWorks MCP Server...'
$zipUrl = "https://github.com/$Repo/archive/refs/heads/main.zip"
try {
    $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
    if ($release.zipball_url) {
        $zipUrl = $release.zipball_url
        Write-Ok "Latest release: $($release.tag_name)"
    }
} catch {
    Write-Ok 'No published release found; using latest main branch.'
}

$tmpZip = Join-Path $env:TEMP 'solidworks-mcp.zip'
$tmpExtract = Join-Path $env:TEMP 'solidworks-mcp-extract'
Invoke-WebRequest $zipUrl -OutFile $tmpZip -UseBasicParsing
if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force }
Expand-Archive $tmpZip -DestinationPath $tmpExtract

# The zip contains a single versioned root folder — find it by pyproject.toml
$srcDir = Get-ChildItem $tmpExtract -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'pyproject.toml') } | Select-Object -First 1
if (-not $srcDir) { throw 'Downloaded archive did not contain the expected project files.' }

New-Item -ItemType Directory -Force $InstallDir | Out-Null
# Preserve the user's saved parts (app\workspace) across updates
$workspaceKeep = $null
if (Test-Path (Join-Path $AppDir 'workspace')) {
    $workspaceKeep = Join-Path $InstallDir 'workspace-keep'
    if (Test-Path $workspaceKeep) { Remove-Item $workspaceKeep -Recurse -Force }
    Move-Item (Join-Path $AppDir 'workspace') $workspaceKeep
}
if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
Move-Item $srcDir.FullName $AppDir
if ($workspaceKeep) { Move-Item $workspaceKeep (Join-Path $AppDir 'workspace') }
Remove-Item $tmpZip -Force
Remove-Item $tmpExtract -Recurse -Force
Write-Ok "Installed to: $AppDir"

# --- 3. Python environment -------------------------------------------------
Write-Step 'Setting up Python environment (uv downloads Python if needed)...'
if (Test-Path $VenvDir) { Remove-Item $VenvDir -Recurse -Force }
& $uv venv $VenvDir --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python environment.' }
$venvPython = Join-Path $VenvDir 'Scripts\python.exe'
& $uv pip install --python $venvPython $AppDir
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python dependencies.' }

# Sanity check the imports that matter (pywin32 COM, MCP SDK, Pillow)
& $venvPython -c "import win32com.client, mcp, PIL"
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed — dependencies did not import cleanly.' }
Write-Ok 'Python environment ready.'

# --- 4. Register with Claude Desktop --------------------------------------
Write-Step 'Registering with Claude Desktop...'

# Classic install path, then Microsoft Store (MSIX) install path
$cfgDir = Join-Path $env:APPDATA 'Claude'
if (-not (Test-Path $cfgDir)) {
    $msix = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Packages') -Directory -Filter 'Claude*' -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if ($msix) {
        $candidate = Join-Path $msix.FullName 'LocalCache\Roaming\Claude'
        if (Test-Path $candidate) { $cfgDir = $candidate }
    }
}
if (-not (Test-Path $cfgDir)) {
    New-Item -ItemType Directory -Force $cfgDir | Out-Null
    Write-Host '    NOTE: Claude Desktop config folder was not found — created one.' -ForegroundColor Yellow
    Write-Host '    If Claude Desktop is not installed yet, get it from https://claude.ai/download' -ForegroundColor Yellow
}

$cfgPath = Join-Path $cfgDir 'claude_desktop_config.json'
$config = $null
if (Test-Path $cfgPath) {
    Copy-Item $cfgPath "$cfgPath.backup" -Force
    Write-Ok "Backed up existing config to claude_desktop_config.json.backup"
    $raw = Get-Content $cfgPath -Raw
    if ($raw -and $raw.Trim()) { $config = $raw | ConvertFrom-Json }
}
if (-not $config) { $config = [pscustomobject]@{} }
if (-not ($config.PSObject.Properties.Name -contains 'mcpServers') -or -not $config.mcpServers) {
    $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{}) -Force
}

$serverEntry = [pscustomobject]@{
    command = $venvPython
    args    = @((Join-Path $AppDir 'server.py'))
}
$config.mcpServers | Add-Member -NotePropertyName solidworks -NotePropertyValue $serverEntry -Force

# BOM-less UTF-8: PS 5.1's Out-File -Encoding utf8 writes a BOM, which some
# JSON parsers reject
[IO.File]::WriteAllText($cfgPath, ($config | ConvertTo-Json -Depth 20),
                        (New-Object System.Text.UTF8Encoding $false))
Write-Ok "Updated: $cfgPath"

# --- Done ------------------------------------------------------------------
Write-Host ''
Write-Host 'Done! Final steps:' -ForegroundColor White
Write-Host '  1. Restart Claude Desktop completely (File -> Exit, then reopen).'
Write-Host '  2. Make sure SolidWorks is installed. Starting it before Claude helps.'
Write-Host '  3. Ask Claude: "Create a 50mm cube in SolidWorks".'
Write-Host ''
