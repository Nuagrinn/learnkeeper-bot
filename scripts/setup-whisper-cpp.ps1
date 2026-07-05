param(
    [string]$Version = "v1.9.1",
    [ValidateSet("tiny", "base", "small", "medium")]
    [string]$Model = "base",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $InstallDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\tools\whisper.cpp"))
}

$binDir = Join-Path $InstallDir "bin"
$modelDir = Join-Path $InstallDir "models"
$tmpDir = Join-Path $InstallDir ".tmp"

New-Item -ItemType Directory -Force -Path $binDir, $modelDir, $tmpDir | Out-Null

$zipPath = Join-Path $tmpDir "whisper-bin-x64.zip"
$binUrl = "https://github.com/ggml-org/whisper.cpp/releases/download/$Version/whisper-bin-x64.zip"
$modelPath = Join-Path $modelDir "ggml-$Model.bin"
$modelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$Model.bin"

Write-Host "Downloading whisper.cpp $Version..."
Invoke-WebRequest -Uri $binUrl -OutFile $zipPath

Write-Host "Extracting whisper.cpp..."
Expand-Archive -Path $zipPath -DestinationPath $binDir -Force

if (-not (Test-Path $modelPath)) {
    Write-Host "Downloading GGML model ggml-$Model.bin..."
    Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath
}
else {
    Write-Host "Model already exists: $modelPath"
}

$exe = Get-ChildItem -Path $binDir -Recurse -Filter "whisper-cli.exe" |
    Select-Object -First 1

if (-not $exe) {
    throw "whisper-cli.exe was not found in $binDir after extraction."
}

Remove-Item -Force -Path $zipPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "whisper.cpp is ready."
Write-Host "Set these values in .env:"
Write-Host "STT_PROVIDER=whisper_cpp"
Write-Host "STT_WHISPER_CPP_BIN=$($exe.FullName)"
Write-Host "STT_WHISPER_CPP_MODEL=$modelPath"
Write-Host "FFMPEG_BIN=ffmpeg"
