# Frontend dev server (http://localhost:3000). Proxies /api/* to the backend on 127.0.0.1:8000.
# First time: cd frontend\web; npm install   (npm cache is kept inside the project: .cache\npm)
$root = Resolve-Path "$PSScriptRoot\..\.."
$env:npm_config_cache = "$root\.cache\npm"; $env:TEMP = "$root\.tmp"; $env:TMP = "$root\.tmp"
$env:NEXT_TELEMETRY_DISABLED = "1"
Set-Location "$root\frontend\web"
& .\node_modules\.bin\next.cmd dev -p 3000
