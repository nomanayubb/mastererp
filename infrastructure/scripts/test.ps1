# Run the full quality gate (lint, types, import boundaries, tests) with all temp/cache files on D:.
$root = Resolve-Path "$PSScriptRoot\..\.."
$env:TEMP = "$root\.tmp"; $env:TMP = "$root\.tmp"
New-Item -ItemType Directory -Force "$root\.tmp" | Out-Null
Set-Location "$root\backend"
$py = "$root\.venv\Scripts"
& "$py\python.exe" -m ruff check ueos tests
& "$py\python.exe" -m mypy ueos --ignore-missing-imports
& "$py\lint-imports.exe"
& "$py\python.exe" -m pytest -q
