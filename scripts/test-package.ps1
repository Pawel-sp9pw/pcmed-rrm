[CmdletBinding()]
param([string]$Archive = (Join-Path $PSScriptRoot '..\artifacts\pcmed-windows-mvp.zip'))
$ErrorActionPreference = 'Stop'
$expectedHash = ((Get-Content -LiteralPath ($Archive + '.sha256') -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $expectedHash) { throw 'Package checksum mismatch.' }
$package = [System.IO.Compression.ZipFile]::OpenRead([System.IO.Path]::GetFullPath($Archive))
try {
    $required = @('Agent/PcMed.Agent.exe', 'Agent/Notifier/PcMed.Notifier.exe', 'Gateway/PcMed.Gateway.exe', 'Agent/appsettings.json', 'Gateway/appsettings.json', 'Install-Agent.ps1', 'Install-Gateway.ps1', 'Scripts/install-windows.ps1', 'Scripts/package-security.ps1', 'manifest.json', 'WDROZENIE.md', 'PROXMOX.md')
    foreach ($name in $required) {
        $entry = @($package.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq $name })
        if ($entry.Count -ne 1 -or $entry[0].Length -eq 0) { throw "Missing or empty package entry: $name" }
        if ($name.EndsWith('.exe')) {
            $stream = $entry[0].Open()
            try { if ($stream.ReadByte() -ne 77 -or $stream.ReadByte() -ne 90) { throw "Invalid Windows executable: $name" } }
            finally { $stream.Dispose() }
        }
    }
    foreach ($entry in $package.Entries) {
        if ($entry.FullName -match '(^|[/\\])(\.env|credential\.bin|journal\.bin)$|\.(pfx|key)$') { throw "Secret file in package: $($entry.FullName)" }
    }
    $manifestEntry = $package.Entries | Where-Object { $_.FullName.Replace('\','/') -eq 'manifest.json' }
    $reader = [IO.StreamReader]::new($manifestEntry.Open())
    try { $manifest = @($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
    foreach ($item in $manifest) {
        $entry = @($package.Entries | Where-Object { $_.FullName.Replace('\','/') -ceq $item.path })
        if ($entry.Count -ne 1) { throw "Manifest file absent: $($item.path)" }
        $stream = $entry[0].Open()
        try {
            $algorithm = [Security.Cryptography.SHA256]::Create()
            try { $actual = [Convert]::ToHexString($algorithm.ComputeHash($stream)) } finally { $algorithm.Dispose() }
            if ($actual -ne $item.sha256) { throw "Invalid manifest hash: $($item.path)" }
        } finally { $stream.Dispose() }
    }
    if (@($package.Entries | Where-Object { $_.Length -gt 0 -and $_.FullName -notmatch '(^|[/\\])manifest.json$' }).Count -ne $manifest.Count) { throw 'Unlisted ZIP entry.' }
} finally { $package.Dispose() }
Write-Host 'Deployment package verified: EXE files, configuration, installers, guide and checksum.'
