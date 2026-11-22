# Start the UEOS dev stack. Everything (venv, caches, temp, database files) lives inside the project folder.
$root = Resolve-Path "$PSScriptRoot\..\.."
$env:PIP_CACHE_DIR = "$root\.cache\pip"
$env:TEMP = "$root\.tmp"; $env:TMP = "$root\.tmp"
New-Item -ItemType Directory -Force "$root\.tmp", "$root\.cache\pip" | Out-Null
& "$root\.venv\Scripts\python.exe" -m ueos.devserver
