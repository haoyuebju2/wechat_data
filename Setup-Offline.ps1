# Setup may access public package/source hosts. Runtime remains default-deny.
param([switch]$SourcesOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime\python.exe'))) {
    & (Join-Path $projectRoot 'scripts\Prepare-Runtime.ps1')
}
$python = Join-Path $projectRoot '.runtime\python.exe'
& $python -I -B (Join-Path $projectRoot 'scripts\prepare_sources.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned source preparation failed.' }
if ($SourcesOnly) { return }
$venvPython = Join-Path $projectRoot '.upstream-runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -I -m venv (Join-Path $projectRoot '.upstream-runtime')
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated Python environment creation failed.' }
}
& $venvPython -I -m pip install -r (Join-Path $projectRoot 'upstream_local\offline-requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Pinned Python dependency installation failed.' }
$sourcePath = Join-Path $projectRoot 'upstream_local\src'
& $venvPython -I -B (Join-Path $projectRoot 'scripts\configure_source_path.py') $sourcePath
if ($LASTEXITCODE -ne 0) { throw 'Local source path setup failed.' }
Get-Command npm.cmd -ErrorAction Stop | Out-Null
foreach ($relative in @('upstream_local\frontend', 'upstream_local\desktop')) {
    Push-Location (Join-Path $projectRoot $relative)
    try {
        & npm.cmd ci --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw 'Pinned npm installation failed.' }
    } finally { Pop-Location }
}
Push-Location (Join-Path $projectRoot 'upstream_local\desktop')
try {
    & node.exe .\node_modules\electron\install.js
    if ($LASTEXITCODE -ne 0) { throw 'Electron download/verification failed.' }
} finally { Pop-Location }
Push-Location (Join-Path $projectRoot 'upstream_local\frontend')
try {
    & npm.cmd run generate
    if ($LASTEXITCODE -ne 0) { throw 'Offline frontend build failed.' }
} finally { Pop-Location }
. (Join-Path $projectRoot 'scripts\Upstream-Firewall-Policy.ps1')
Assert-UpstreamArtifacts
Write-Output 'Setup complete. Install the firewall rules, then use Start-Offline.cmd.'
