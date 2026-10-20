#Requires -RunAsAdministrator
#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$CentralUrl = 'https://172.20.0.8:38443',
    [string]$LanDnsName,
    [string]$LanSubnet,
    [string]$LanAddress,
    [string]$CertificateThumbprint,
    [string]$CentralCertificateSha256,
    [ValidateRange(1024,49151)][int]$GatewayPort = 38444,
    [string[]]$ArtifactHosts
)
$ErrorActionPreference = 'Stop'
if (-not $LanAddress) { $LanAddress = Read-Host 'Staly adres LAN bramki, np. 192.168.20.10' }
if (-not $LanSubnet) { $LanSubnet = Read-Host 'Podsiec LAN, np. 192.168.20.0/24' }
if (-not $CertificateThumbprint) { $CertificateThumbprint = Read-Host 'Thumbprint certyfikatu TLS z kluczem w LocalMachine\My (SAN musi zawierac adres IP bramki)' }
if (-not $ArtifactHosts) { $ArtifactHosts = @(([uri]$CentralUrl).DnsSafeHost) }
& (Join-Path $PSScriptRoot 'Scripts\install-windows.ps1') -Component Gateway -PublishDirectory (Join-Path $PSScriptRoot 'Gateway') -Endpoint $CentralUrl -ArtifactHosts $ArtifactHosts -LanDnsName $LanDnsName -LanSubnet $LanSubnet -LanAddress $LanAddress -CertificateThumbprint $CertificateThumbprint -ServerCertificateSha256 $CentralCertificateSha256 -GatewayPort $GatewayPort
