# Replaces the placeholder organisation name with your GitHub username (whole word only).
param([Parameter(Mandatory = $true)][string]$Owner)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding $false
Get-ChildItem -Recurse -File -Force -Include *.md, *.yml, *.yaml, *.json, *.toml, *.tf, CODEOWNERS |
  Where-Object { $_.FullName -notmatch '\\(node_modules|\.git)\\' -and $_.Name -ne 'package-lock.json' } |
  ForEach-Object {
    $old = [IO.File]::ReadAllText($_.FullName)
    $new = $old -replace '@your-org/(security|platform)', "@$Owner" -replace '\byour-org\b', $Owner
    if ($new -ne $old) {
      [IO.File]::WriteAllText($_.FullName, $new, $utf8)
      Write-Host "updated $($_.FullName)"
    }
  }
Write-Host "Done. Owner is now '$Owner'."
