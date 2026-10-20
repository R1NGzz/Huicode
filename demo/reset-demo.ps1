$ErrorActionPreference = "Stop"
$workspace = Join-Path $PSScriptRoot "workspace"
$fixture = Join-Path $PSScriptRoot "fixture-project"

if (Test-Path -LiteralPath $workspace) {
    Remove-Item -LiteralPath $workspace -Recurse -Force
}
Copy-Item -LiteralPath $fixture -Destination $workspace -Recurse
Write-Host "演示项目已重置：$workspace"
