param([switch]$SkipFirewall,[switch]$NoShortcuts,[switch]$EnableAutoStart)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$projectRoot=Split-Path -Parent $PSScriptRoot
$release=Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION.json') -Raw|ConvertFrom-Json
if(-not [Environment]::Is64BitOperatingSystem){throw 'Windows x64 is required.'}
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$nodeDirectory=Join-Path $projectRoot '.node-runtime'
if(Test-Path -LiteralPath $nodeDirectory){throw 'A dedicated Node runtime already exists. Use a new empty installation directory.'}
$nodeZip=Join-Path $projectRoot 'node-runtime-download.zip'
Write-Output 'Downloading the pinned official Node.js runtime...'
Invoke-WebRequest -Uri ("https://nodejs.org/dist/v"+$release.node_version+"/node-v"+$release.node_version+"-win-x64.zip") -OutFile $nodeZip -UseBasicParsing -TimeoutSec 180
if((Get-FileHash -LiteralPath $nodeZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $release.node_zip_sha256){throw 'Node runtime checksum mismatch; nothing from this archive was executed.'}
Expand-Archive -LiteralPath $nodeZip -DestinationPath $nodeDirectory
$nodeBin=Join-Path $nodeDirectory ("node-v"+$release.node_version+'-win-x64')
$env:PATH=$nodeBin+';'+$env:PATH
if((& (Join-Path $nodeBin 'node.exe') --version) -ne ('v'+$release.node_version)){throw 'Node runtime version mismatch.'}
Write-Output 'Installing pinned public sources and dependencies; no WeChat data is read...'
& (Join-Path $projectRoot 'Setup-Offline.ps1')
if($LASTEXITCODE -ne 0){throw 'Source and dependency setup failed.'}
$launcher=Join-Path $projectRoot 'WeChatDataMonitor.exe'
$compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /r:System.Windows.Forms.dll ('/out:'+$launcher) (Join-Path $PSScriptRoot 'LocalLauncher.cs')
if($LASTEXITCODE -ne 0 -or -not(Test-Path -LiteralPath $launcher)){throw 'Local launcher compilation failed.'}
if(-not $NoShortcuts){
    $shell=New-Object -ComObject WScript.Shell
    $folders=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))
    if($EnableAutoStart){$folders+= [Environment]::GetFolderPath('Startup')}
    foreach($folder in $folders){
        $shortcutPath=Join-Path $folder ('WeChatDataMonitor '+$release.version+'.lnk')
        if(Test-Path -LiteralPath $shortcutPath){throw 'An existing shortcut has the same name; it was not overwritten.'}
        $shortcut=$shell.CreateShortcut($shortcutPath);$shortcut.TargetPath=$launcher;$shortcut.WorkingDirectory=$projectRoot;$shortcut.Description='WeChatDataMonitor local viewer';$shortcut.Save()
    }
}
$firewallReady=$false
if(-not $SkipFirewall){
    Write-Output 'Configuring this installation firewall rules; Windows may ask for administrator confirmation...'
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'Enable-Upstream-Firewall.ps1')+'"'
    $admin=Start-Process -FilePath (Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe') -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
    if($admin.ExitCode -ne 0){throw 'Program files are installed, but firewall setup did not complete. Run Enable-Offline-Firewall.cmd as administrator before starting.'}
    . (Join-Path $PSScriptRoot 'Upstream-Firewall-Policy.ps1')
    Assert-UpstreamFirewall
    $firewallReady=$true
}
$record=@{version=$release.version;installed_at_utc=[DateTime]::UtcNow.ToString('o');firewall_ready=$firewallReady;automatic_start=[bool]$EnableAutoStart}
[IO.File]::WriteAllText((Join-Path $projectRoot 'installed-version.json'),($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
Write-Output 'Installation complete. Start WeChatDataMonitor.exe; configure your own WeChat account in the application.'
