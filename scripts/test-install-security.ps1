[CmdletBinding()]
param([string]$Package = (Join-Path $PSScriptRoot '..\artifacts\windows'))
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'package-security.ps1')
Test-PcMedPackage -Root $Package
if ((ConvertTo-PcMedIpv4Number -Address ([Net.IPAddress]::Parse('192.168.20.10'))) -ne 3232240650) { throw 'IPv4 conversion failed.' }
$tokens = $null
$errors = $null
Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -Recurse | ForEach-Object {
    [Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors) { throw "Invalid PowerShell: $($_.FullName): $errors" }
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('pcmed-package-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    Copy-Item -Path (Join-Path $Package '*') -Destination $temporary -Recurse
    Test-PcMedPackage -Root $temporary
    Add-Content -LiteralPath (Join-Path $temporary 'WDROZENIE.md') -Value 'modified'
    $rejected = $false
    try { Test-PcMedPackage -Root $temporary } catch { $rejected = $true }
    if (-not $rejected) { throw 'Tampered package was accepted.' }
    Copy-Item -LiteralPath (Join-Path $Package 'WDROZENIE.md') -Destination $temporary -Force
    Set-Content -LiteralPath (Join-Path $temporary 'unexpected.dll') -Value 'unexpected'
    $rejected = $false
    try { Test-PcMedPackage -Root $temporary } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unlisted package file was accepted.' }
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    $parent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'pcmed-package-test-*') { throw 'Unsafe temporary cleanup path.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host 'Install security verified: package integrity, added-file rejection, IPv4 conversion and script syntax.'
