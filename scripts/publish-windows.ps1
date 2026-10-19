[CmdletBinding()]
param([string]$Output = (Join-Path $PSScriptRoot '..\artifacts\windows'))
$ErrorActionPreference = 'Stop'
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
Write-Host "Published Windows binaries to $Output. Requires .NET 10 Desktop and ASP.NET Core runtimes."
