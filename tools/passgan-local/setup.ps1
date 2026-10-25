$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$passgan = Join-Path $root "PassGAN"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop, then reopen PowerShell."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows, then reopen PowerShell."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is not running. Start Docker Desktop and rerun this script."
}

if (-not (Test-Path $passgan)) {
    git clone https://github.com/brannondorsey/PassGAN.git $passgan
    if ($LASTEXITCODE -ne 0) { throw "Could not clone the upstream PassGAN repository." }
} else {
    Write-Host "Using existing local checkout: $passgan"
}

$checkpointMeta = Join-Path $passgan "pretrained\checkpoints\195000.ckpt.meta"
if (-not (Test-Path $checkpointMeta)) {
    $localPretrained = Join-Path $env:USERPROFILE "Downloads\PassGAN\PassGAN-master\pretrained"
    if (Test-Path $localPretrained) {
        Write-Host "Copying the existing pretrained model into the isolated checkout..."
        $targetPretrained = Join-Path $passgan "pretrained"
        New-Item -ItemType Directory -Force -Path $targetPretrained | Out-Null
        Copy-Item -Path (Join-Path $localPretrained "*") -Destination $targetPretrained -Recurse -Force
    }
}

if (-not (Test-Path $checkpointMeta)) {
    throw "Pretrained checkpoint not found. Copy your pretrained folder to '$passgan\pretrained' and rerun."
}

Write-Host "Building isolated legacy TensorFlow image..."
docker build -t passgan-legacy -f (Join-Path $root "Dockerfile") $root
if ($LASTEXITCODE -ne 0) { throw "Docker image build failed." }

Write-Host "Converting legacy Python 2 syntax in the isolated checkout..."
docker run --rm -v "$($passgan):/app" -w /app passgan-legacy python -m lib2to3 -w -n tflib sample.py models.py utils.py
if ($LASTEXITCODE -ne 0) { throw "Python 2-to-3 conversion failed." }

Write-Host "Applying CPU and pickle compatibility fixes..."
docker run --rm -v "$($passgan):/app" -v "$($root):/patches" -w /app passgan-legacy python /patches/patch_cpu_conv1d.py /app
if ($LASTEXITCODE -ne 0) { throw "Compatibility patch failed." }

Write-Host "Running a small CPU smoke test (64 generated samples)..."
docker run --rm -v "$($passgan):/app" -w /app passgan-legacy python sample.py --input-dir pretrained --checkpoint pretrained/checkpoints/195000.ckpt --output generated_test.txt --num-samples 64 --batch-size 64 --seq-length 10 --layer-dim 128
if ($LASTEXITCODE -ne 0) { throw "PassGAN smoke test failed. Review the error above." }

Write-Host ""
Write-Host "Smoke test completed. Output: $passgan\generated_test.txt"
