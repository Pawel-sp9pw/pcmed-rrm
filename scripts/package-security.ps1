function Test-PcMedPackage {
    param([Parameter(Mandatory)][string]$Root, [switch]$PassThru)
    $rootPath = (Resolve-Path -LiteralPath $Root).Path
    $ancestor = Get-Item -LiteralPath $rootPath
    while ($ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Package path must not contain links or reparse points.' }
        $ancestor = $ancestor.Parent
    }
    $files = @(Get-ChildItem -LiteralPath $rootPath -Recurse -Force)
    if ($files | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Package contains a link or reparse point.' }
    $manifest = @(Get-Content -LiteralPath (Join-Path $rootPath 'manifest.json') -Raw | ConvertFrom-Json)
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $manifest) {
        if ($entry.path -notmatch '^[a-zA-Z0-9_./-]+$' -or $entry.path -match '(^|/)\.\.?(/|$)' -or $entry.path.StartsWith('/') -or -not $names.Add($entry.path)) { throw 'Invalid package manifest path.' }
        $path = Join-Path $rootPath $entry.path
        if ($entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Package integrity failure: $($entry.path)" }
    }
    $actual = @($files | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne (Join-Path $rootPath 'manifest.json') })
    if ($actual.Count -ne $manifest.Count) { throw 'Unlisted files in package. Extract a fresh package into an empty folder.' }
    if ($PassThru) { return $manifest }
}

function Assert-PcMedProtectedPath {
    param([Parameter(Mandatory)][string]$Path)
    $item = Get-Item -LiteralPath $Path
    while ($item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installation path must not contain links or reparse points.' }
        $acl = Get-Acl -LiteralPath $item.FullName
        $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
        if ($owner -notin @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')) { throw "Unsafe owner of installation path: $($item.FullName)" }
        foreach ($rule in $acl.Access) {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            $write = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
            if ($rule.AccessControlType -eq 'Allow' -and ($rule.FileSystemRights -band $write) -and $sid -notin @('S-1-5-18','S-1-5-32-544','S-1-3-0','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')) { throw "Unsafe writable installation path: $($item.FullName)" }
        }
        if ($item.FullName -eq $env:ProgramFiles) { break }
        $item = $item.Parent
    }
}

function ConvertTo-PcMedIpv4Number {
    param([Parameter(Mandatory)][Net.IPAddress]$Address)
    $bytes = $Address.GetAddressBytes()
    if ($bytes.Length -ne 4) { throw 'IPv4 address required.' }
    [uint32]$numeric = 0
    foreach ($octet in $bytes) { $numeric = ($numeric -shl 8) -bor $octet }
    return $numeric
}
