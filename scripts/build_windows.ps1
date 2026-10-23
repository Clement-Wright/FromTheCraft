param([string]$OutputDirectory = 'dist')

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$outputRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
if (-not $outputRoot.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must stay inside the project folder.' }
$portableFolder = Join-Path $outputRoot 'FromTheCraft'
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
& $pythonExe setup.py build_ext --inplace
if ($LASTEXITCODE -ne 0) { throw 'Native mesh sampler build failed.' }
& $pythonExe -c 'from fromthecraft import _mesh_native'
if ($LASTEXITCODE -ne 0) { throw 'Native mesh sampler is missing from this build.' }
& $pythonExe -m PyInstaller --noconfirm --clean --windowed --onedir --name FromTheCraft --distpath $outputRoot --paths src --collect-data fromthecraft --collect-all UnityPy --collect-data archspec --exclude-module fmod_toolkit --exclude-module pyfmodex --copy-metadata litemapy --add-data 'build/THIRD_PARTY_LICENSES;THIRD_PARTY_LICENSES' scripts/portable_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
Copy-Item -LiteralPath README.md -Destination (Join-Path $portableFolder 'README.md')
Copy-Item -LiteralPath COPYING -Destination (Join-Path $portableFolder 'COPYING')
New-Item -ItemType Directory -Path (Join-Path $portableFolder 'assets/readme') -Force | Out-Null
Copy-Item -LiteralPath MOD_COMPATIBILITY.md -Destination (Join-Path $portableFolder 'MOD_COMPATIBILITY.md')
Copy-Item -LiteralPath assets/readme/workbench.png -Destination (Join-Path $portableFolder 'assets/readme/workbench.png')
Copy-Item -LiteralPath assets/readme/slopes-copycats.png -Destination (Join-Path $portableFolder 'assets/readme/slopes-copycats.png')
Copy-Item -LiteralPath examples -Destination $portableFolder -Recurse
Write-Host "Portable application: $portableFolder\FromTheCraft.exe"
Write-Host 'Keep the entire FromTheCraft folder together.'
