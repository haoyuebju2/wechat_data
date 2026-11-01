. "$PSScriptRoot\Upstream-Firewall-Policy.ps1"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Enable-Upstream-Offline-Firewall.cmd as administrator once.' }
$expectedRules = @(Get-UpstreamRules)
$existing = @($expectedRules | ForEach-Object { Get-NetFirewallRule -Name $_.Name -ErrorAction SilentlyContinue })
if ($existing.Count -eq $expectedRules.Count) { Assert-UpstreamFirewall; Write-Host 'Existing upstream-offline rules verified.'; exit 0 }
if ($existing.Count) { throw 'Partial configuration exists. Inspect these project rules before continuing.' }
foreach ($expected in $expectedRules) {
    if (-not (Test-Path -LiteralPath $expected.Program)) { throw 'Prepare all offline runtime components first.' }
}
foreach ($expected in $expectedRules) {
    New-NetFirewallRule -Name $expected.Name -DisplayName $expected.Name -Group $rulePrefix -Program $expected.Program `
        -Direction $expected.Direction -Action Block -Enabled True -Profile Any -Protocol Any -LocalAddress Any -RemoteAddress Any | Out-Null
}
Assert-UpstreamFirewall
Write-Host 'Dedicated Python and Electron inbound/outbound block rules are verified.'
