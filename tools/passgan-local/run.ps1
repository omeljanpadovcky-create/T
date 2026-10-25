$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$passgan = Join-Path $root "PassGAN"
$output = Join-Path $passgan "generated_samples.txt"

if (-not (Test-Path (Join-Path $passgan "sample.py"))) {
    throw "PassGAN checkout not found. Run .\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $passgan "pretrained\checkpoints\195000.ckpt.meta"))) {
    throw "Pretrained checkpoint not found. Run .\setup.ps1 first."
}

Write-Host "Generating 1,024 local test samples..."
docker run --rm -v "$($passgan):/app" -w /app passgan-legacy python sample.py --input-dir pretrained --checkpoint pretrained/checkpoints/195000.ckpt --output generated_samples.txt --num-samples 1024 --batch-size 64 --seq-length 10 --layer-dim 128
if ($LASTEXITCODE -ne 0) {
    throw "PassGAN generation failed. Review the TensorFlow traceback above."
}
if (-not (Test-Path $output)) {
    throw "The command finished but the output file was not found: $output"
}

Write-Host ""
Write-Host "Generation completed. Output saved to:"
Write-Host $output
Write-Host "Sample preview (first 10 lines):"
Get-Content $output -TotalCount 10
