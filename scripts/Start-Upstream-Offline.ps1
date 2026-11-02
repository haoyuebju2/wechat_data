. "$PSScriptRoot\Upstream-Firewall-Policy.ps1"
Assert-UpstreamFirewall
Assert-UpstreamArtifacts
& (Join-Path $PSScriptRoot 'Build-LocalCdnWorker.ps1')
$electron = Join-Path $projectRoot 'upstream_local\desktop\node_modules\electron\dist\electron.exe'
$env:WECHAT_OFFLINE_OS_POLICY = 'checked'
$env:ELECTRON_RUN_AS_NODE = $null
$desktopArgument = '"' + (Join-Path $projectRoot 'upstream_local\desktop') + '"'
$desktopProcess = Start-Process -FilePath $electron -ArgumentList $desktopArgument -WorkingDirectory $projectRoot -WindowStyle Normal -PassThru
Write-Output ('Offline desktop process: ' + $desktopProcess.Id)
