#Requires -RunAsAdministrator
#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$CentralUrl,
    [string]$LanDnsName,
    [string]$LanSubnet,
    [string[]]$ArtifactHosts
)
$ErrorActionPreference = 'Stop'
if (-not $CentralUrl) { $CentralUrl = Read-Host 'Adres HTTPS centrali, np. https://rmm.pcmed.lan' }
if (-not $LanDnsName) { $LanDnsName = Read-Host 'Nazwa DNS bramki w LAN, np. gateway.firma.lan' }
if (-not $LanSubnet) { $LanSubnet = Read-Host 'Podsiec LAN, np. 192.168.20.0/24' }
if (-not $ArtifactHosts) { $ArtifactHosts = @(([uri]$CentralUrl).DnsSafeHost) }
& (Join-Path $PSScriptRoot 'Scripts\install-windows.ps1') -Component Gateway -PublishDirectory (Join-Path $PSScriptRoot 'Gateway') -Endpoint $CentralUrl -ArtifactHosts $ArtifactHosts -LanDnsName $LanDnsName -LanSubnet $LanSubnet
