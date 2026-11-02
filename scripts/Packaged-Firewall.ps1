param([ValidateSet('Check','Configure')][string]$Mode='Check')
$env:PSModulePath=Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/Modules'
Import-Module NetSecurity -ErrorAction Stop
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$bytes = [Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())
$hashProvider = [Security.Cryptography.SHA256]::Create()
try { $digest = [BitConverter]::ToString($hashProvider.ComputeHash($bytes)).Replace('-', '').Substring(0, 12) }
finally { $hashProvider.Dispose() }
$rulePrefix = "OfflineWechatPackaged-$digest"

function Get-UpstreamPrograms {
    @('WeChatDataMonitor.exe','resources\python\python.exe','resources\python\pythonw.exe') | ForEach-Object { Join-Path $projectRoot $_ }
}
function Get-UpstreamRules {
    $index = 0
    foreach ($program in Get-UpstreamPrograms) {
        foreach ($direction in @('Inbound', 'Outbound')) {
            [PSCustomObject]@{Name="$rulePrefix-$index-$direction";Program=$program;Direction=$direction}
        }
        $index++
    }
}
function Assert-UpstreamFirewall {
    if ((Get-Service MpsSvc).Status -ne 'Running') { throw 'Windows Firewall must be running.' }
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($profiles.Count -ne 3 -or @($profiles | Where-Object {-not $_.Enabled -or $_.AllowLocalFirewallRules -eq 'False'}).Count) {
        throw 'Firewall profiles or local rule enforcement are disabled.'
    }
    foreach ($expected in Get-UpstreamRules) {
        $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $expected.Name -ErrorAction SilentlyContinue
        if (-not $rule -or $rule.Enabled -ne 'True' -or $rule.Action -ne 'Block' -or $rule.Direction -ne $expected.Direction -or $rule.Profile -ne 'Any') {
            throw 'Required upstream-offline firewall rules are absent or changed. Run Enable-Upstream-Offline-Firewall.cmd as administrator.'
        }
        $application = $rule | Get-NetFirewallApplicationFilter
        $address = $rule | Get-NetFirewallAddressFilter
        $port = $rule | Get-NetFirewallPortFilter
        $service = $rule | Get-NetFirewallServiceFilter
        $interface = $rule | Get-NetFirewallInterfaceFilter
        $interfaceType = $rule | Get-NetFirewallInterfaceTypeFilter
        if ($application.Program -ne $expected.Program -or ($application.Package -and $application.Package -ne 'Any') -or
            $address.LocalAddress -ne 'Any' -or $address.RemoteAddress -ne 'Any' -or $port.Protocol -ne 'Any' -or
            $port.LocalPort -ne 'Any' -or $port.RemotePort -ne 'Any' -or $service.Service -ne 'Any' -or
            $interface.InterfaceAlias -ne 'Any' -or $interfaceType.InterfaceType -ne 'Any') { throw 'Firewall rule scope is too narrow.' }
    }
}

if($Mode -eq 'Configure') {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=[Security.Principal.WindowsPrincipal]::new($identity)
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator confirmation is required.'}
    foreach($expected in Get-UpstreamRules){
        if(-not(Test-Path -LiteralPath $expected.Program)){throw 'Packaged executable is missing.'}
        if(-not(Get-NetFirewallRule -Name $expected.Name -ErrorAction SilentlyContinue)){
            New-NetFirewallRule -Name $expected.Name -DisplayName $expected.Name -Group $rulePrefix -Program $expected.Program -Direction $expected.Direction -Action Block -Enabled True -Profile Any -Protocol Any -LocalAddress Any -RemoteAddress Any | Out-Null
        }
    }
}
Assert-UpstreamFirewall
Write-Output 'Packaged application firewall policy verified.'
