[CmdletBinding()]
param([string]$Output = (Join-Path $PSScriptRoot '..\artifacts\windows'))
$ErrorActionPreference = 'Stop'
$Output = [System.IO.Path]::GetFullPath($Output)
$root = Join-Path $PSScriptRoot '..\windows'
Push-Location $root
try {
    foreach ($component in 'Agent','Gateway','Notifier') {
        $project = Join-Path $root "PcMed.$component\PcMed.$component.csproj"
        & dotnet publish $project -c Release -r win-x64 --self-contained false -o (Join-Path $Output $component)
        if ($LASTEXITCODE -ne 0) { throw "Publish failed: $component" }
    }
} finally {
    Pop-Location
}
$notifierTarget = Join-Path $Output 'Agent\Notifier'
New-Item -ItemType Directory -Path $notifierTarget -Force | Out-Null
Copy-Item -Path (Join-Path $Output 'Notifier\*') -Destination $notifierTarget -Recurse -Force
$scriptsTarget = Join-Path $Output 'Scripts'
New-Item -ItemType Directory -Path $scriptsTarget -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-windows.ps1') -Destination $scriptsTarget -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'distribution\*.ps1') -Destination $Output -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\docs\WDROZENIE.md') -Destination (Join-Path $Output 'WDROZENIE.md') -Force
$archive = Join-Path (Split-Path -Parent $Output) 'pcmed-windows-mvp.zip'
Compress-Archive -Path (Join-Path $Output '*') -DestinationPath $archive -Force
$checksum = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath ($archive + '.sha256') -Value ($checksum + '  ' + (Split-Path -Leaf $archive)) -Encoding ascii
Write-Host "Published Windows binaries to $Output. Requires .NET 10 Desktop and ASP.NET Core runtimes."
Write-Host "Deployment guide, install scripts and ZIP: $archive"
