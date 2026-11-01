$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bytes = [Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())
$hashProvider = [Security.Cryptography.SHA256]::Create()
try { $digest = [BitConverter]::ToString($hashProvider.ComputeHash($bytes)).Replace('-', '').Substring(0, 12) }
finally { $hashProvider.Dispose() }
$rulePrefix = "OfflineWechatUpstream-$digest"

function Get-UpstreamPrograms {
    @('.runtime\python.exe', '.runtime\pythonw.exe', '.upstream-runtime\Scripts\python.exe', '.upstream-runtime\Scripts\pythonw.exe',
      'upstream_local\desktop\node_modules\electron\dist\electron.exe') | ForEach-Object { Join-Path $projectRoot $_ }
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

function Assert-UpstreamArtifacts {
    $manifestPath = Join-Path $PSScriptRoot 'offline-runtime-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Pinned offline runtime manifest is missing.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($artifact in $manifest.artifacts.PSObject.Properties) {
        $target = [IO.Path]::GetFullPath((Join-Path $projectRoot $artifact.Name))
        if (-not $target.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid runtime integrity path.' }
        if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $artifact.Value) {
            throw 'A pinned runtime artifact is missing or changed. Review and rebuild before starting.'
        }
    }
}
