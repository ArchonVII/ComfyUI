[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('flux2-klein9b', 'qwen-edit-2511')]
    [string] $Model,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$')]
    [string] $Character,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$')]
    [string] $RunName,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z][A-Za-z0-9_-]{2,63}$')]
    [string] $TriggerToken,

    [Parameter(Mandatory)]
    [string] $Dit,

    [Parameter(Mandatory)]
    [string] $Vae,

    [Parameter(Mandatory)]
    [string] $TextEncoder,

    [string] $DatasetDir,
    [string] $ControlDir,
    [switch] $DryRun,
    [switch] $ApproveOutput,
    [ValidateRange(1, 1000)]
    [int] $MinimumFreeGiB = 50
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TrainerRoot = 'C:\tools\image\trainers\musubi-tuner'
$TrainingRoot = 'C:\tools\image\training\characters'
$TrainerPython = Join-Path $TrainerRoot '.venv\Scripts\python.exe'
$Renderer = Join-Path $PSScriptRoot 'render_musubi_config.py'
$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ApprovedLoraRoot = Join-Path $RepositoryRoot 'models\loras\trained\characters'
$RunDir = Join-Path (Join-Path (Join-Path $TrainingRoot 'runs') $RunName) $Model
$OutputDir = Join-Path (Join-Path (Join-Path $TrainingRoot 'outputs') $RunName) $Model
$DatasetDir = if ($DatasetDir) { $DatasetDir } else { Join-Path (Join-Path (Join-Path $TrainingRoot 'datasets') $Character) 'targets' }

function Assert-UnderRoot {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $Root,
        [Parameter(Mandatory)] [string] $Label
    )
    $resolvedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    $resolvedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must remain under '$resolvedRoot'; received '$resolvedPath'."
    }
}

function Assert-FreeSpace {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [int] $MinimumGiB
    )
    $probe = [System.IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $probe)) {
        $parent = [System.IO.Directory]::GetParent($probe)
        if ($null -eq $parent) {
            throw "Cannot resolve a disk for '$Path'."
        }
        $probe = $parent.FullName
    }
    $drive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($probe))
    $availableGiB = $drive.AvailableFreeSpace / 1GB
    if ($availableGiB -lt $MinimumGiB) {
        throw ("Disk guard: training needs at least {0} GiB free; only {1:N1} GiB is available." -f $MinimumGiB, $availableGiB)
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [Parameter()] [string[]] $ArgumentList = @()
    )
    Write-Host ('> ' + $FilePath + ' ' + ($ArgumentList -join ' '))
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

Assert-UnderRoot -Path $DatasetDir -Root $TrainingRoot -Label 'Dataset directory'
Assert-UnderRoot -Path $RunDir -Root $TrainingRoot -Label 'Run directory'
Assert-UnderRoot -Path $OutputDir -Root $TrainingRoot -Label 'Output directory'
if ($ControlDir) {
    Assert-UnderRoot -Path $ControlDir -Root $TrainingRoot -Label 'Control directory'
}
if ($Model -eq 'qwen-edit-2511' -and -not $ControlDir) {
    throw "Qwen Edit 2511 requires -ControlDir with one or more matching starting images per target."
}
if ($Model -eq 'flux2-klein9b' -and $ControlDir) {
    throw "This Klein character template is caption-only; do not pass -ControlDir."
}
if (-not (Test-Path -LiteralPath $TrainerPython -PathType Leaf)) {
    throw "Isolated Musubi Python is missing at '$TrainerPython'. Run install-musubi.ps1 first."
}
if ($env:VIRTUAL_ENV -and ([System.IO.Path]::GetFullPath($env:VIRTUAL_ENV) -ne [System.IO.Path]::GetFullPath((Split-Path -Parent (Split-Path -Parent $TrainerPython))))) {
    throw "Another virtual environment is active. Deactivate it before starting the isolated trainer."
}

Assert-FreeSpace -Path $TrainingRoot -MinimumGiB $MinimumFreeGiB

$rendererArgs = @(
    '-I', $Renderer,
    '--model', $Model,
    '--dataset-dir', $DatasetDir,
    '--run-dir', $RunDir,
    '--run-name', $RunName,
    '--trigger-token', $TriggerToken,
    '--dit', $Dit,
    '--vae', $Vae,
    '--text-encoder', $TextEncoder
)
if ($ControlDir) {
    $rendererArgs += @('--control-dir', $ControlDir)
}

$ramGiB = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
if ($Model -eq 'qwen-edit-2511' -and $ramGiB -lt 64) {
    Write-Warning ("Qwen Edit block swap recommends 64 GiB RAM; this host reports {0:N1} GiB. Paging or failure is possible." -f $ramGiB)
}
elseif ($Model -eq 'flux2-klein9b' -and $ramGiB -lt 32) {
    Write-Warning ("FLUX.2 Klein 9B training with {0:N1} GiB RAM is experimental and may page heavily." -f $ramGiB)
}
Write-Warning "This low-memory lane targets approximately 16 GB VRAM and remains experimental. Keep batch size 1 and close other GPU workloads."

if ($DryRun) {
    $rendererArgs += '--dry-run'
    Invoke-Checked -FilePath $TrainerPython -ArgumentList $rendererArgs
    return
}

$expectedOutput = Join-Path $OutputDir ($RunName + '.safetensors')
if (Test-Path -LiteralPath $expectedOutput) {
    throw "Training output already exists and will not be overwritten: $expectedOutput"
}

Invoke-Checked -FilePath $TrainerPython -ArgumentList $rendererArgs

$DatasetConfig = Join-Path $RunDir 'dataset.toml'
$TrainConfig = Join-Path $RunDir 'train.toml'
$SourceRoot = Join-Path $TrainerRoot 'src\musubi_tuner'
if ($Model -eq 'flux2-klein9b') {
    $modelVersion = 'klein-base-9b'
    $latentScript = 'flux_2_cache_latents.py'
    $textScript = 'flux_2_cache_text_encoder_outputs.py'
    $trainScript = 'flux_2_train_network.py'
    $textFp8Flag = '--fp8_text_encoder'
}
else {
    $modelVersion = 'edit-2511'
    $latentScript = 'qwen_image_cache_latents.py'
    $textScript = 'qwen_image_cache_text_encoder_outputs.py'
    $trainScript = 'qwen_image_train_network.py'
    $textFp8Flag = '--fp8_vl'
}

Push-Location $RunDir
try {
    Invoke-Checked -FilePath $TrainerPython -ArgumentList @(
        (Join-Path $SourceRoot $latentScript),
        '--dataset_config', $DatasetConfig,
        '--vae', $Vae,
        '--model_version', $modelVersion,
        '--vae_dtype', 'bfloat16'
    )
    Invoke-Checked -FilePath $TrainerPython -ArgumentList @(
        (Join-Path $SourceRoot $textScript),
        '--dataset_config', $DatasetConfig,
        '--text_encoder', $TextEncoder,
        '--batch_size', '1',
        '--model_version', $modelVersion,
        $textFp8Flag
    )
    Invoke-Checked -FilePath $TrainerPython -ArgumentList @(
        '-m', 'accelerate.commands.launch',
        '--num_cpu_threads_per_process', '1',
        '--mixed_precision', 'bf16',
        (Join-Path $SourceRoot $trainScript),
        '--config_file', $TrainConfig
    )
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $expectedOutput -PathType Leaf)) {
    throw "Musubi returned successfully but the expected LoRA was not found: $expectedOutput"
}

$completion = @{
    completed_utc = [DateTime]::UtcNow.ToString('o')
    model = $Model
    output = $expectedOutput
    run_name = $RunName
} | ConvertTo-Json
$completion | Set-Content -LiteralPath (Join-Path $RunDir 'training-complete.json') -Encoding utf8

if ($ApproveOutput) {
    New-Item -ItemType Directory -Path $ApprovedLoraRoot -Force | Out-Null
    $approved = Join-Path $ApprovedLoraRoot ($RunName + '-' + $Model + '.safetensors')
    if (Test-Path -LiteralPath $approved) {
        throw "Approved LoRA already exists and will not be overwritten: $approved"
    }
    Copy-Item -LiteralPath $expectedOutput -Destination $approved
    Write-Host "Approved LoRA copied to: $approved"
}
else {
    Write-Host "Training output remains staged locally. Re-run with -ApproveOutput only after reviewing it."
}
