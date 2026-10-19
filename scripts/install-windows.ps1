#Requires -RunAsAdministrator
#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Agent', 'Gateway')][string]$Component,
    [Parameter(Mandatory)][string]$PublishDirectory,
    [Parameter(Mandatory)][string]$Endpoint,
    [string[]]$ArtifactHosts = @(),
    [string]$LanDnsName,
    [string]$LanSubnet,
    [switch]$DirectVpn
)
$ErrorActionPreference = 'Stop'
$origin = [uri]$Endpoint
if ($origin.Scheme -ne 'https' -or $origin.AbsolutePath -ne '/' -or $origin.UserInfo -or $origin.Query -or $origin.Fragment) {
    throw 'Endpoint must be an HTTPS origin.'
}
$source = (Resolve-Path -LiteralPath $PublishDirectory).Path
$target = Join-Path $env:ProgramFiles "PcMed\$Component"
$serviceName = "PcMed$Component"
if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) { throw 'Service already exists; stop it and perform a deliberate upgrade.' }
if (Test-Path -LiteralPath $target) { throw 'Installation folder already exists.' }
if ($Component -eq 'Gateway' -and (-not $LanDnsName -or -not $LanSubnet)) { throw 'Gateway requires LanDnsName and LanSubnet, for example gateway.client.lan and 192.168.20.0/24.' }
$executable = "PcMed.$Component.exe"
if (-not (Test-Path -LiteralPath (Join-Path $source $executable))) { throw "Missing $executable in publish directory." }
New-Item -ItemType Directory -Path $target | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse
$acl = Get-Acl -LiteralPath $target
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new([System.Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
$readRule = [System.Security.AccessControl.FileSystemAccessRule]::new([System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'), 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($readRule)
Set-Acl -LiteralPath $target -AclObject $acl
$configPath = Join-Path $target 'appsettings.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable
if ($Component -eq 'Agent') {
    $config.Agent.Endpoint = $Endpoint
    $config.Agent.ArtifactHosts = $ArtifactHosts
    $config.Agent.UseGateway = -not $DirectVpn
} else {
    $config.Gateway.Upstream = $Endpoint
    $config.Gateway.ArtifactHosts = $ArtifactHosts
    $config.Kestrel.Endpoints.LanHttps.Certificate.Subject = $LanDnsName
    $config.AllowedHosts = $LanDnsName
}
$config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $configPath -Encoding utf8
$binary = Join-Path $target $executable
if ($Component -eq 'Agent') { & $binary --enroll } else { & $binary --provision }
if ($LASTEXITCODE -ne 0) { throw 'Provisioning failed. No service has been started.' }
New-Service -Name $serviceName -BinaryPathName ('"' + $binary + '"') -DisplayName "PC MED $Component" -StartupType Automatic | Out-Null
if ($Component -eq 'Agent' -and (Test-Path -LiteralPath (Join-Path $target 'Notifier\PcMed.Notifier.exe'))) {
    New-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name PcMedNotifier -Value ('"' + (Join-Path $target 'Notifier\PcMed.Notifier.exe') + '"') -PropertyType String -Force | Out-Null
}
if ($Component -eq 'Gateway') {
    New-NetFirewallRule -DisplayName 'PC MED Gateway LAN HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7443 -RemoteAddress $LanSubnet -Program $binary -Profile Domain,Private | Out-Null
}
Start-Service -Name $serviceName
Write-Host "$serviceName installed. Check the Windows event log and the central panel."
