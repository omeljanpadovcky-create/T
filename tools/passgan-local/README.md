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
3. Run:

    Set-ExecutionPolicy -Scope Process Bypass
    .\tools\passgan-local\setup.ps1

The setup script clones the upstream PassGAN source into this folder, builds the legacy container, converts Python 2 syntax in the local clone, applies a CPU layout compatibility patch, and runs a 64-sample smoke test. The cloned source folder is ignored by Git and is not committed.

## Checkpoint note
The script looks for `pretrained/checkpoints/195000.ckpt.meta` in the cloned source. If missing, it attempts to copy the pretrained folder from:

`%USERPROFILE%\Downloads\PassGAN\PassGAN-master\pretrained`

If that folder is not present, copy your existing pretrained directory into `tools\passgan-local\PassGAN\pretrained`, then rerun the script. The checkpoint's `.meta`, `.index`, and `.data-00000-of-00001` files are required.

## Generate and inspect samples
From the repository root, run:

    .\tools\passgan-local\run.ps1

The runner removes the previous output first (the upstream sampler appends by default), generates 1,024 samples, validates the non-empty line count, previews the first 10 lines, and runs the diagnostics script. Output is saved to:

`tools\passgan-local\PassGAN\generated_samples.txt`

To inspect an existing output without generating again:

    .\tools\passgan-local\analyze_samples.ps1

The PowerShell report includes file size, non-ASCII bytes and lines, duplicates, line lengths, and control-character checks.

### Inspect the character vocabulary
To check whether unusual characters are part of the model vocabulary and inspect the file's actual UTF-8 decoding, first download `inspect_vocab.py` into `tools\passgan-local`, then run from that directory:

    docker run --rm -v "${PWD}\PassGAN:/app" -v "${PWD}:/tools" passgan-legacy python /tools/inspect_vocab.py --input-dir /app/pretrained --samples /app/generated_samples.txt

The report prints vocabulary entries using Python `repr`, checks UTF-8 decoding, and shows control-character examples. Non-ASCII characters may be part of the model vocabulary; they are not automatically evidence of corruption. Avoid re-encoding or replacing characters until the vocabulary and raw bytes have been checked.

## Troubleshooting
- Docker daemon not running: start Docker Desktop, wait until it reports running, and rerun.
- Git not found: install Git for Windows, reopen PowerShell, and rerun.
- Checkpoint missing: follow the checkpoint note above.
- TensorFlow version warning: the old TensorFlow wheel may emit a compile/runtime Python-version warning. The warning alone is not fatal; check the final exit status and output count.
- CPU convolution error: rerun the setup script to apply the patch to the isolated clone. It does not alter the original PassGAN folder in Downloads.
- Unexpected characters in output: run both diagnostic scripts before changing encoding.

## Scope
This is an experimental compatibility wrapper, not a maintained or secure production service. TensorFlow 1.4.1 is end-of-life; run it only in the disposable Docker container and do not mount unrelated project directories or secrets.
