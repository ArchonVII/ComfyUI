[CmdletBinding()]
param(
    [switch] $DryRun,
    [ValidateRange(1, 500)]
    [int] $MinimumTrainerFreeGiB = 20,
    [ValidateRange(1, 1000)]
    [int] $MinimumTrainingFreeGiB = 50
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$MusubiRevision = '8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6'
$TrainerRoot = 'C:\tools\image\trainers\musubi-tuner'
$TrainingRoot = 'C:\tools\image\training\characters'
$TrainerVenv = Join-Path $TrainerRoot '.venv'
$TrainerPython = Join-Path $TrainerVenv 'Scripts\python.exe'
$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ApprovedLoraRoot = Join-Path $RepositoryRoot 'models\loras\trained\characters'

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
        throw ("Disk guard: '{0}' needs at least {1} GiB free; only {2:N1} GiB is available." -f $Path, $MinimumGiB, $availableGiB)
    }
    Write-Host ("Disk guard passed for '{0}': {1:N1} GiB free." -f $Path, $availableGiB)
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)] [string] $FilePath,
        [Parameter()] [string[]] $ArgumentList = @()
    )

    Write-Host ('> ' + $FilePath + ' ' + ($ArgumentList -join ' '))
    if ($DryRun) {
        return
    }
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath"
    }
}

if ($env:VIRTUAL_ENV -and ([System.IO.Path]::GetFullPath($env:VIRTUAL_ENV) -ne [System.IO.Path]::GetFullPath($TrainerVenv))) {
    throw "Another virtual environment is active. Deactivate it before installing the isolated trainer."
}

Assert-FreeSpace -Path (Split-Path -Parent $TrainerRoot) -MinimumGiB $MinimumTrainerFreeGiB
Assert-FreeSpace -Path (Split-Path -Parent $TrainingRoot) -MinimumGiB $MinimumTrainingFreeGiB

$Git = (Get-Command git -ErrorAction Stop).Source
$Uv = (Get-Command uv -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $TrainerRoot)) {
    if (-not $DryRun) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $TrainerRoot) -Force | Out-Null
    }
    Invoke-Checked -FilePath $Git -ArgumentList @(
        'clone',
        'https://github.com/kohya-ss/musubi-tuner.git',
        $TrainerRoot
    )
}
elseif (-not (Test-Path -LiteralPath (Join-Path $TrainerRoot '.git'))) {
    throw "Trainer root exists but is not a Git checkout: $TrainerRoot"
}

if (Test-Path -LiteralPath (Join-Path $TrainerRoot '.git')) {
    $dirty = & $Git -C $TrainerRoot status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the existing trainer checkout."
    }
    if ($dirty) {
        throw "Trainer checkout has local changes. Preserve or remove them before pinning revision $MusubiRevision."
    }
}

Invoke-Checked -FilePath $Git -ArgumentList @('-C', $TrainerRoot, 'fetch', 'origin', $MusubiRevision)
Invoke-Checked -FilePath $Git -ArgumentList @('-C', $TrainerRoot, 'checkout', '--detach', $MusubiRevision)

if (-not (Test-Path -LiteralPath $TrainerPython)) {
    Invoke-Checked -FilePath $Uv -ArgumentList @(
        'venv',
        '--python', '3.12',
        '--seed',
        $TrainerVenv
    )
}

Invoke-Checked -FilePath $Uv -ArgumentList @(
    'pip', 'install',
    '--python', $TrainerPython,
    '--index-url', 'https://download.pytorch.org/whl/cu128',
    'torch', 'torchvision'
)
Invoke-Checked -FilePath $Uv -ArgumentList @(
    'pip', 'install',
    '--python', $TrainerPython,
    '--editable', $TrainerRoot
)

if (-not $DryRun) {
    foreach ($directory in @(
        (Join-Path $TrainingRoot 'datasets'),
        (Join-Path $TrainingRoot 'runs'),
        (Join-Path $TrainingRoot 'cache'),
        (Join-Path $TrainingRoot 'outputs'),
        $ApprovedLoraRoot
    )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

Invoke-Checked -FilePath $TrainerPython -ArgumentList @(
    '-I',
    '-c',
    'import accelerate, torch, musubi_tuner; print(torch.__version__); print(torch.cuda.is_available())'
)

if (-not $DryRun) {
    $installedRevision = (& $Git -C $TrainerRoot rev-parse HEAD).Trim()
    if ($installedRevision -ne $MusubiRevision) {
        throw "Installed revision '$installedRevision' does not match required revision '$MusubiRevision'."
    }
}

Write-Host "Musubi trainer installation plan is pinned to $MusubiRevision with isolated venv $TrainerVenv."
