$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$workspace = Join-Path $PSScriptRoot "workspace"
$fixture = Join-Path $PSScriptRoot "fixture-project"
$config = Join-Path $PSScriptRoot "huicode.demo.yaml.example"
$python = "python"
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
}
elseif (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ was not found."
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $workspace)) {
    Copy-Item -LiteralPath $fixture -Destination $workspace -Recurse
}

$env:PYTHONPATH = $repo
Push-Location $workspace
try {
    & $python -m huicode --demo --config $config
}
finally {
    Pop-Location
}
