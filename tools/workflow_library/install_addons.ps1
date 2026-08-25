<#
.SYNOPSIS
    Clone the recommended ComfyUI addons into custom_nodes.

.DESCRIPTION
    Installs the three extensions from docs/workflow-prompt-addons-research.md
    that live inside ComfyUI. SmartGallery is deliberately not installed here:
    it is a separate application, not a custom node.

    Existing clones are left alone unless -Update is passed, and nothing is
    deleted. Run from anywhere; pass -ComfyRoot if this script is not sitting
    inside the ComfyUI tree.

.EXAMPLE
    .\install_addons.ps1 -ComfyRoot C:\tools\image\ComfyUI

.EXAMPLE
    .\install_addons.ps1 -ComfyRoot C:\tools\image\ComfyUI -Update
#>
[CmdletBinding()]
param(
    [string]$ComfyRoot,
    [switch]$Update,
    [switch]$SkipWildcards
)

$ErrorActionPreference = 'Stop'

$addons = @(
    @{
        Name = 'comfyui-adaptiveprompts'
        Url  = 'https://github.com/Alectriciti/comfyui-adaptiveprompts.git'
        Why  = 'Wildcards, variables and adaptive RNG - replaces the arch-pt node chain'
    },
    @{
        Name = 'ComfyUI-Autocomplete-Plus'
        Url  = 'https://github.com/newtextdoc1111/ComfyUI-Autocomplete-Plus.git'
        Why  = 'Tag autocomplete and the related-tag panel in every text widget'
    },
    @{
        Name = 'comfyui-g-workflows'
        Url  = 'https://github.com/AI4VFX/comfyui-g-workflows.git'
        Why  = 'Workflow browser with thumbnails and sidecar tags'
    }
)

if (-not $ComfyRoot) {
    $ComfyRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}
if (-not (Test-Path (Join-Path $ComfyRoot 'custom_nodes'))) {
    throw "No custom_nodes folder under '$ComfyRoot'. Pass -ComfyRoot explicitly."
}

$customNodes = Join-Path $ComfyRoot 'custom_nodes'
Write-Host "ComfyUI root: $ComfyRoot" -ForegroundColor Cyan
Write-Host ""

foreach ($addon in $addons) {
    $target = Join-Path $customNodes $addon.Name
    Write-Host ("{0,-30} {1}" -f $addon.Name, $addon.Why) -ForegroundColor Gray

    if (Test-Path $target) {
        if ($Update) {
            Write-Host "  updating..." -NoNewline
            git -C $target pull --ff-only 2>&1 | Out-Null
            Write-Host " done" -ForegroundColor Green
        }
        else {
            Write-Host "  already present, skipping (use -Update to pull)" -ForegroundColor Yellow
        }
        continue
    }

    Write-Host "  cloning..." -NoNewline
    git clone --depth 1 $addon.Url $target 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        continue
    }
    Write-Host " done" -ForegroundColor Green

    $requirements = Join-Path $target 'requirements.txt'
    if (Test-Path $requirements) {
        Write-Host "  installing requirements..." -NoNewline
        python -m pip install -q -r $requirements
        Write-Host " done" -ForegroundColor Green
    }
}

if (-not $SkipWildcards) {
    Write-Host ""
    $wildcardTarget = Join-Path $customNodes 'comfyui-adaptiveprompts\wildcards'
    $wildcardSource = Join-Path $ComfyRoot 'wildcards\archpt'
    if ((Test-Path $wildcardSource) -and (Test-Path (Split-Path $wildcardTarget))) {
        Write-Host "Copying arch-pt wildcards into adaptiveprompts..." -NoNewline
        New-Item -ItemType Directory -Force -Path $wildcardTarget | Out-Null
        $archptTarget = Join-Path $wildcardTarget 'archpt'
        # Copy-Item -Recurse onto an existing folder of the same name nests it,
        # so a second run would create archpt\archpt. Clear it first.
        if (Test-Path $archptTarget) { Remove-Item -Recurse -Force $archptTarget }
        Copy-Item -Recurse -Force $wildcardSource $archptTarget
        Write-Host " done" -ForegroundColor Green
    }
    else {
        Write-Host "Wildcard export not found at $wildcardSource" -ForegroundColor Yellow
        Write-Host "  run: python -m tools.workflow_library.export_wildcards" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart the ComfyUI server (not just a browser refresh)."
Write-Host "  2. Hard-refresh the browser (Ctrl+F5)."
Write-Host "  3. If ComfyUI-Custom-Scripts is installed, disable its autocomplete -"
Write-Host "     it binds the same text widgets as Autocomplete-Plus."
Write-Host "  4. SmartGallery DAM is a separate app, not a custom node:"
Write-Host "     https://github.com/biagiomaf/smart-comfyui-gallery"
