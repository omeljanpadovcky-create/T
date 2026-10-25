$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$passgan = Join-Path $root "PassGAN"
$output = Join-Path $passgan "generated_samples.txt"
$expectedSamples = 1024

if (-not (Test-Path (Join-Path $passgan "sample.py"))) {
    throw "PassGAN checkout not found. Run .\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $passgan "pretrained\checkpoints\195000.ckpt.meta"))) {
    throw "Pretrained checkpoint not found. Run .\setup.ps1 first."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Start/install Docker Desktop, then reopen PowerShell."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is not running. Start Docker Desktop and rerun this script."
}

# Upstream sample.py opens the output in append mode, so remove the old file
# first to make the reported sample count accurate on every run.
if (Test-Path $output) {
    Remove-Item -LiteralPath $output -Force
}

Write-Host "Generating $expectedSamples local test samples..."
docker run --rm -v "$($passgan):/app" -w /app passgan-legacy python sample.py --input-dir pretrained --checkpoint pretrained/checkpoints/195000.ckpt --output generated_samples.txt --num-samples $expectedSamples --batch-size 64 --seq-length 10 --layer-dim 128
if ($LASTEXITCODE -ne 0) {
    throw "PassGAN generation failed. Review the TensorFlow traceback above."
}
if (-not (Test-Path $output)) {
    throw "The command finished but the output file was not found: $output"
}

$sampleLines = @(Get-Content -LiteralPath $output | Where-Object { $_.Length -gt 0 })
if ($sampleLines.Count -ne $expectedSamples) {
    throw "Expected $expectedSamples non-empty samples, but found $($sampleLines.Count). The output may be incomplete."
}

Write-Host ""
Write-Host "Generation completed. Output saved to:"
Write-Host $output
Write-Host "Sample preview (first 10 lines):"
Get-Content -LiteralPath $output -TotalCount 10

Write-Host ""
Write-Host "Running output diagnostics..."
& (Join-Path $root "analyze_samples.ps1") -Path $output
if ($LASTEXITCODE -ne 0) {
    throw "Sample diagnostics failed."
}
