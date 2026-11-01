# Development/setup only. The application never calls this downloader.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$archivePath = Join-Path $projectRoot 'python-3.14.10-amd64.zip'
$expectedHash = 'cc28026a650970cc1570bb127312f1f9634eb67abfe157ae6ca1acbbc627d091'
if (Test-Path -LiteralPath $runtimeDir) { throw 'Runtime directory already exists; refusing to overwrite it.' }
if (-not (Test-Path -LiteralPath $archivePath)) {
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.zip' -OutFile $archivePath -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Official Python runtime SHA-256 mismatch. Nothing will be executed.'
}
Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimeDir
$exe = Join-Path $runtimeDir 'python.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Runtime archive has an unexpected layout.' }
& $exe -I -S -B (Join-Path $PSScriptRoot 'runtime_check.py')
if ($LASTEXITCODE -ne 0) { throw 'Runtime self-check failed.' }
Write-Host 'Dedicated official Python runtime is ready. No PATH, registry, or system Python changes were made.'
