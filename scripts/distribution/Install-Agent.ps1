#Requires -RunAsAdministrator
#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$GatewayUrl,
    [string]$GatewayCertificateSha256,
    [string]$ScanCidr,
    [ValidateRange(1024,49151)][int]$GatewayPort = 38444
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Scripts\package-security.ps1')
Test-PcMedPackage -Root $PSScriptRoot
if (-not $GatewayCertificateSha256) { $GatewayCertificateSha256 = Read-Host 'SHA-256 certyfikatu bramki otrzymany od administratora (64 znaki)' }
if (($GatewayCertificateSha256 -replace '[: ]','') -notmatch '^[a-fA-F0-9]{64}$') { throw 'Nieprawidlowy odcisk SHA-256 certyfikatu.' }
if (-not $GatewayUrl) {
    Write-Host "Szukam bramki w lokalnej sieci na TCP $GatewayPort. Nie wysylam tokenow ani hasel."
    $arguments = @('--discover','--certificate-sha256',$GatewayCertificateSha256,'--port',"$GatewayPort")
    if ($ScanCidr) { $arguments += @('--scan-cidr',$ScanCidr) }
    $result = & (Join-Path $PSScriptRoot 'Agent\PcMed.Agent.exe') @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Skanowanie nie powiodlo sie. Sprawdz CA, odcisk, podsiec i zapore lub podaj GatewayUrl.' }
    $found = @($result | ConvertFrom-Json)
    if ($found.Count -ne 1) { throw "Znaleziono $($found.Count) zaufanych bramek. Podaj jednoznaczny GatewayUrl; nie wybieram losowo." }
    $GatewayUrl = [string]$found[0]
    if ((Read-Host "Znaleziono $GatewayUrl. Wpisz TAK, aby zainstalowac klienta") -cne 'TAK') { throw 'Anulowano instalacje.' }
}
& (Join-Path $PSScriptRoot 'Scripts\install-windows.ps1') -Component Agent -PublishDirectory (Join-Path $PSScriptRoot 'Agent') -Endpoint $GatewayUrl -ServerCertificateSha256 $GatewayCertificateSha256
