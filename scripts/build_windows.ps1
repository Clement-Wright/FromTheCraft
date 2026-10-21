$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Create .venv and install the project dev dependencies first. See README.md.' }
Push-Location -LiteralPath (Join-Path $projectRoot 'ui')
try {
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
& $pythonExe scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
& $pythonExe -m PyInstaller --noconfirm --clean --windowed --onedir --name FromTheCraft --paths src --collect-data fromthecraft --copy-metadata litemapy --add-data 'build/THIRD_PARTY_LICENSES;THIRD_PARTY_LICENSES' scripts/portable_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
Copy-Item -LiteralPath README.md -Destination 'dist/FromTheCraft/README.md'
Copy-Item -LiteralPath COPYING -Destination 'dist/FromTheCraft/COPYING'
New-Item -ItemType Directory -Path 'dist/FromTheCraft/docs' -Force | Out-Null
Copy-Item -LiteralPath docs/implementation.md -Destination 'dist/FromTheCraft/docs/implementation.md'
Write-Host 'Portable application: dist\FromTheCraft\FromTheCraft.exe'
Write-Host 'Keep the entire FromTheCraft folder together.'
