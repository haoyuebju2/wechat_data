$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$source=Join-Path $projectRoot 'upstream_local/desktop/src/LocalCdnWorker.cs'
$directory=Join-Path $projectRoot 'upstream_local/desktop/cdn-worker'
$binary=Join-Path $directory 'LocalCdnWorker.exe'
$artifact=Join-Path $directory 'artifact.json'
$sourceHash=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
if((Test-Path -LiteralPath $artifact) -and (Test-Path -LiteralPath $binary)) {
    $record=Get-Content -LiteralPath $artifact -Raw|ConvertFrom-Json
    if($record.source_sha256 -eq $sourceHash -and $record.binary_sha256 -eq (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()){return}
}
$compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if(-not(Test-Path -LiteralPath $compiler)){throw 'The local Microsoft .NET compiler is required for the original-image worker.'}
New-Item -ItemType Directory -Path $directory -Force|Out-Null
& $compiler /nologo /target:exe /platform:x64 /optimize+ /r:System.Web.Extensions.dll /r:System.Security.dll ('/out:'+$binary) $source
if($LASTEXITCODE -ne 0){throw 'Local image worker compilation failed.'}
$record=@{format='local-cdn-worker/1';source_sha256=$sourceHash;binary_sha256=(Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()}
[IO.File]::WriteAllText($artifact,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
