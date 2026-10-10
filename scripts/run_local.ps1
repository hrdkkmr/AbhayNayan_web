$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Venv = Join-Path $Root '.venv'
$Python = Join-Path $Venv 'Scripts/python.exe'

if (-not (Test-Path $Python)) {
    $PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { 'python' }
    & $PythonBin -m venv $Venv
}
if (-not (Test-Path $Python)) { throw 'Could not create the Python virtual environment.' }
$PythonReady = $false
try {
    & $Python -c 'import fastapi, uvicorn' *> $null
    $PythonReady = ($LASTEXITCODE -eq 0)
} catch { $PythonReady = $false }
if (-not $PythonReady) { & $Python -m pip install -r (Join-Path $Root 'requirements.txt') }

# Load server-only settings from .env (gitignored). Variables already set in the shell win; values are never printed.
$EnvFile = Join-Path $Root '.env'
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' -and $Matches[2] -ne '') {
            $name = $Matches[1]; $value = $Matches[2].Trim('"').Trim("'")
            if (-not [Environment]::GetEnvironmentVariable($name)) { [Environment]::SetEnvironmentVariable($name, $value, 'Process') }
        }
    }
}
$env:PYTHONPATH = (Join-Path $Root 'backend') + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { '' })
if (-not $env:ABHAYNAYAN_DB_PATH) { $env:ABHAYNAYAN_DB_PATH = Join-Path $Root 'backend/data/abhaynayan.sqlite3' }
$HostName = if ($env:HOST) { $env:HOST } else { '0.0.0.0' }
$Port = if ($env:PORT) { $env:PORT } else { '8000' }
Set-Location $Root
& $Python -m uvicorn app.main:app --app-dir backend --host $HostName --port $Port
