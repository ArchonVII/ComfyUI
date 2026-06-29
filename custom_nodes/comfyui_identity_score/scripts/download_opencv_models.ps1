$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ModelDir = Join-Path $Root "models"
New-Item -ItemType Directory -Force $ModelDir | Out-Null

$Files = @(
    @{
        Url = "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx"
        Out = "face_detection_yunet_2023mar.onnx"
    },
    @{
        Url = "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx"
        Out = "face_recognition_sface_2021dec.onnx"
    }
)

foreach ($File in $Files) {
    $Target = Join-Path $ModelDir $File.Out
    if (Test-Path $Target) {
        Write-Host "exists $Target"
        continue
    }
    Invoke-WebRequest -Uri $File.Url -OutFile $Target
    Write-Host "downloaded $Target"
}
