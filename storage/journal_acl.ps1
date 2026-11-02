param([Parameter(Mandatory=$true)][ValidateSet('ensure','check-file')][string]$Action,
      [Parameter(Mandatory=$true)][string]$Target)
$ErrorActionPreference = 'Stop'
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
$admins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
$allowed = @($current.Value, $system.Value, $admins.Value)
if ($Action -eq 'ensure' -and -not [System.IO.Directory]::Exists($Target)) {
    $parent = [System.IO.Path]::GetDirectoryName($Target)
    if (-not [System.IO.Directory]::Exists($parent)) { throw 'Parent directory missing' }
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($current)
    foreach ($sid in @($current, $system, $admins)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $security.AddAccessRule($rule)
    }
    [System.IO.Directory]::CreateDirectory($Target, $security) | Out-Null
}
$item = Get-Item -LiteralPath $Target -Force
if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point forbidden' }
if ($Action -eq 'ensure' -and -not $item.PSIsContainer) { throw 'Expected directory' }
if ($Action -eq 'check-file' -and $item.PSIsContainer) { throw 'Expected file' }
$acl = Get-Acl -LiteralPath $Target
if ($Action -eq 'ensure' -and -not $acl.AreAccessRulesProtected) { throw 'Inherited directory ACL forbidden' }
$owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
if ($owner -ne $current.Value) { throw 'Unexpected owner' }
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
foreach ($rule in $rules) {
    if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowed) { throw 'Unexpected allowed principal' }
}
foreach ($sid in $allowed) {
    $full = @($rules | Where-Object { $_.IdentityReference.Value -eq $sid -and $_.AccessControlType -eq 'Allow' -and ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq [System.Security.AccessControl.FileSystemRights]::FullControl })
    if ($full.Count -eq 0) { throw 'Missing full control' }
    if ($Action -eq 'ensure' -and -not @($full | Where-Object { ($_.InheritanceFlags -band [System.Security.AccessControl.InheritanceFlags]::ObjectInherit) -ne 0 }).Count) { throw 'Files must inherit ACL' }
}
