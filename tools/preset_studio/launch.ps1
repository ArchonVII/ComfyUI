param(
    [string]$Runtime = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path,
    [int]$Port = 8791
)
$ErrorActionPreference = 'Stop'
$pythonCommand = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$studioUrl = "http://127.0.0.1:$Port"
try {
    $existingStudio = Invoke-RestMethod -Uri "$studioUrl/api/health" -TimeoutSec 2
    if ($existingStudio.app -eq 'preset-studio') {
        Write-Output "Preset Studio is already running: $studioUrl"
        return
    }
} catch { }
$studioData = Join-Path $Runtime 'user/preset_studio'
New-Item -ItemType Directory -Path $studioData -Force | Out-Null
$studioScript = Join-Path $PSScriptRoot 'service.py'
Start-Process -FilePath $pythonCommand -ArgumentList @("`"$studioScript`"", '--runtime', "`"$Runtime`"", '--port', "$Port") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioData 'server.log') -RedirectStandardError (Join-Path $studioData 'server-error.log') | Out-Null
Write-Output "Starting Preset Studio: $studioUrl"
