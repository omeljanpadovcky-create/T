# PassGAN local lab (experimental)

This folder adds an optional, local-only PassGAN experiment alongside MYSHKA ETSY AI. It is not imported by the Etsy app and is not part of the Vercel deployment. Upstream source and model checkpoints are fetched or supplied locally rather than committed here.

Use only for authorized password-strength research on systems and data you own or have explicit permission to test. Generated samples are guesses, not a reliable measure of password strength. Never use generated lists to access third-party accounts.

## Requirements
- Windows 10/11 with Docker Desktop running in Linux-container mode
- Git for Windows
- Internet access for the initial source download
- Pretrained checkpoint files if they are not included by the upstream clone

The legacy TensorFlow 1.4.1 stack is old and intended only for this isolated experiment. It runs CPU-only in the provided container. Do not expose it as a web service or deploy it to Vercel.

## Run on Windows
1. Download this repository's `feature/passgan-local-lab` branch as ZIP and extract it, or check out the branch with Git.
2. Open PowerShell in the extracted repository root.
3. Run these commands:

    Set-ExecutionPolicy -Scope Process Bypass
    .\tools\passgan-local\setup.ps1

The setup script clones the upstream PassGAN source into this folder, builds the legacy container, converts Python 2 syntax in the local clone, applies a CPU layout compatibility patch, and runs a 64-sample smoke test. The cloned source folder is ignored by Git and is not committed.

## Checkpoint note
The script looks for `pretrained/checkpoints/195000.ckpt.meta` in the cloned source. If missing, it attempts to copy the pretrained folder from your existing local copy at:

`%USERPROFILE%\Downloads\PassGAN\PassGAN-master\pretrained`

If that folder is not present, copy your existing pretrained directory into `tools\passgan-local\PassGAN\pretrained`, then rerun the script. The checkpoint's `.meta`, `.index`, and `.data-00000-of-00001` files are required.

## Generate and inspect samples
From the repository root, run:

    .\tools\passgan-local\run.ps1

The runner removes the previous output first (the upstream sampler appends by default), generates 1,024 samples, validates the non-empty line count, previews the first 10 lines, and runs the diagnostics script. Output is saved to:

`tools\passgan-local\PassGAN\generated_samples.txt`

To inspect an existing output without generating again:

    .\tools\passgan-local\analyze_samples.ps1

Or pass a specific file:

    .\tools\passgan-local\analyze_samples.ps1 -Path "C:\path\to\samples.txt"

The report includes file size, non-ASCII byte and line counts, duplicates, line lengths, and control-character checks. Non-ASCII output is a diagnostic signal, not proof of corruption; check the model vocabulary and encoding before changing the generated file.

Generated files and model assets are excluded from Git. These samples are for authorized local password-strength research only; do not use them to attempt access to anyone else's accounts.

## Troubleshooting
- Docker daemon not running: start Docker Desktop, wait until it reports running, and rerun.
- Git not found: install Git for Windows, reopen PowerShell, and rerun.
- Checkpoint missing: follow the checkpoint note above.
- TensorFlow version warning: the old TensorFlow wheel may emit a compile/runtime Python-version warning. The warning alone is not fatal; check the final exit status and output count.
- CPU convolution error: rerun the setup script to apply the patch to the isolated clone. It does not alter the original PassGAN folder in Downloads.
- Unexpected characters in output: run `analyze_samples.ps1` first. Do not blindly replace characters or re-encode the file until the model's character map and actual bytes have been checked.

## Scope
This is an experimental compatibility wrapper, not a maintained or secure production service. TensorFlow 1.4.1 is end-of-life; run it only in the disposable Docker container and do not mount unrelated project directories or secrets.
