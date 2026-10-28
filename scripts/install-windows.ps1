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
    [string]$LanAddress,
    [string]$CertificateThumbprint,
    [string]$ServerCertificateSha256,
    [ValidateRange(1024,49151)][int]$GatewayPort = 38444,
    [switch]$DirectVpn
)
$ErrorActionPreference = 'Stop'
$origin = [uri]$Endpoint
if ($origin.Scheme -ne 'https' -or $origin.AbsolutePath -ne '/' -or $origin.UserInfo -or $origin.Query -or $origin.Fragment) {
    throw 'Endpoint must be an HTTPS origin.'
}
$source = (Resolve-Path -LiteralPath $PublishDirectory).Path
. (Join-Path $PSScriptRoot 'package-security.ps1')
$verifiedManifest = @(Test-PcMedPackage -Root (Split-Path -Parent $source) -PassThru)
if ($ServerCertificateSha256 -and ($ServerCertificateSha256 -replace '[: ]','') -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid server certificate SHA-256.' }
$target = Join-Path $env:ProgramFiles "PcMed\$Component"
$serviceName = "PcMed$Component"
if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) { throw 'Service already exists; stop it and perform a deliberate upgrade.' }
if (Test-Path -LiteralPath $target) { throw 'Installation folder already exists.' }
if ($Component -eq 'Gateway') {
    if (-not $LanAddress -or -not $LanSubnet -or -not $CertificateThumbprint) { throw 'Gateway requires LanAddress, LanSubnet and CertificateThumbprint.' }
    $address = [Net.IPAddress]::Parse($LanAddress)
    $parts = $LanSubnet.Split('/')
    if ($parts.Count -ne 2 -or $parts[1] -notmatch '^([1-9]|[12][0-9]|30)$') { throw 'Use an explicit IPv4 LAN CIDR /1 through /30.' }
    $network = [Net.IPAddress]::Parse($parts[0])
    $bytes = $address.GetAddressBytes()
    if ($bytes.Length -ne 4 -or -not ($bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168))) { throw 'Gateway must bind to a private LAN IPv4 address.' }
    if ($network.GetAddressBytes().Length -ne 4) { throw 'Use IPv4 CIDR.' }
    $prefix = [int]$parts[1]
    $networkBytes = $network.GetAddressBytes()
    if (-not (($networkBytes[0] -eq 10 -and $prefix -ge 8) -or ($networkBytes[0] -eq 172 -and $networkBytes[1] -ge 16 -and $networkBytes[1] -le 31 -and $prefix -ge 12) -or ($networkBytes[0] -eq 192 -and $networkBytes[1] -eq 168 -and $prefix -ge 16))) { throw 'LAN CIDR must be entirely inside an RFC1918 private network.' }
    $mask = [uint32]::MaxValue -shl (32 - $prefix)
    $numeric = ConvertTo-PcMedIpv4Number -Address $address
    $networkNumber = ConvertTo-PcMedIpv4Number -Address $network
    if (($numeric -band $mask) -ne $networkNumber) { throw 'LAN CIDR must be a canonical subnet containing LanAddress.' }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $LanAddress)) { throw 'LAN address is not assigned to this computer.' }
    if (Get-NetTCPConnection -State Listen -LocalPort $GatewayPort -ErrorAction SilentlyContinue) { throw 'Gateway port is already in use. Choose another GatewayPort.' }
}
$executable = "PcMed.$Component.exe"
if (-not (Test-Path -LiteralPath (Join-Path $source $executable))) { throw "Missing $executable in publish directory." }
$parent = Split-Path -Parent $target
if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent | Out-Null }
Assert-PcMedProtectedPath -Path $parent
New-Item -ItemType Directory -Path $target | Out-Null
$acl = Get-Acl -LiteralPath $target
$acl.SetAccessRuleProtection($true, $false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach ($sid in 'S-1-5-18','S-1-5-32-544') {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new([System.Security.Principal.SecurityIdentifier]::new($sid), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
$readRule = [System.Security.AccessControl.FileSystemAccessRule]::new([System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'), 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($readRule)
Set-Acl -LiteralPath $target -AclObject $acl
Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse
$componentFiles = @($verifiedManifest | Where-Object { $_.path.StartsWith($Component + '/', [StringComparison]::Ordinal) })
if (@(Get-ChildItem -LiteralPath $target -Recurse -File).Count -ne $componentFiles.Count) { throw 'Copied component file count differs from verified package.' }
foreach ($entry in $componentFiles) {
    $copied = Join-Path $target $entry.path.Substring($Component.Length + 1)
    if ((Get-FileHash -LiteralPath $copied -Algorithm SHA256).Hash -ne $entry.sha256) { throw 'Package changed during copying. Installation stopped before provisioning.' }
}
$configPath = Join-Path $target 'appsettings.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable
if ($Component -eq 'Agent') {
    $config.Agent.Endpoint = $Endpoint
    $config.Agent.ArtifactHosts = $ArtifactHosts
    $config.Agent.UseGateway = -not $DirectVpn
    $config.Agent.ServerCertificateSha256 = $ServerCertificateSha256
} else {
    & (Join-Path $target 'PcMed.Gateway.exe') --check-certificate --thumbprint $CertificateThumbprint --lan-address $LanAddress
    if ($LASTEXITCODE -ne 0) { throw 'Gateway certificate verification failed.' }
    $config.Gateway.Upstream = $Endpoint
    $config.Gateway.ArtifactHosts = $ArtifactHosts
    $config.Gateway.UpstreamCertificateSha256 = $ServerCertificateSha256
    $config.Gateway.ServerCertificateThumbprint = $CertificateThumbprint
    $config.Gateway.AllowedSubnet = $LanSubnet
    $config.Kestrel.Endpoints.LanHttps.Url = "https://${LanAddress}:$GatewayPort"
    [void]$config.Kestrel.Endpoints.LanHttps.Remove('Certificate')
    $config.AllowedHosts = (@($LanAddress,$LanDnsName) | Where-Object { $_ }) -join ';'
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
    New-NetFirewallRule -DisplayName 'PC MED Gateway LAN HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $LanAddress -LocalPort $GatewayPort -RemoteAddress $LanSubnet -Program $binary -Profile Domain,Private | Out-Null
    New-NetFirewallRule -DisplayName 'PC MED Gateway block public networks' -Direction Inbound -Action Block -Program $binary -Profile Public | Out-Null
}
Start-Service -Name $serviceName
Write-Host "$serviceName installed. Check the Windows event log and the central panel."
