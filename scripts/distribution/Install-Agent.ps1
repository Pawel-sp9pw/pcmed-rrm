#Requires -RunAsAdministrator
#Requires -Version 7.2
[CmdletBinding()]
param([string]$GatewayUrl)
$ErrorActionPreference = 'Stop'
if (-not $GatewayUrl) { $GatewayUrl = Read-Host 'Adres HTTPS bramki, np. https://gateway.firma.lan:7443' }
& (Join-Path $PSScriptRoot 'Scripts\install-windows.ps1') -Component Agent -PublishDirectory (Join-Path $PSScriptRoot 'Agent') -Endpoint $GatewayUrl
