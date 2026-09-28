param(
    [string]$Runtime = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [int]$Port = 8791
)
$ErrorActionPreference = 'Stop'
$pythonCommand = (Get-Command pythonw -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$studioScript = Join-Path $PSScriptRoot 'desktop.py'
Start-Process -FilePath $pythonCommand -ArgumentList @("`"$studioScript`"", '--runtime', "`"$Runtime`"", '--port', "$Port") -WindowStyle Hidden | Out-Null
