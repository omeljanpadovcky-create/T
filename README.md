# PASSGAN Local Lab

**PassGAN is the primary project in this repository.** The root page is a research dashboard for the local generator. The real model is not hosted on Vercel: it uses a legacy TensorFlow container and runs on the user's Windows machine.

## What is included
- Root dashboard for local-run instructions, importing generated output, filtering lines and exporting a TXT file.
- Isolated compatibility scripts in `tools/passgan-local`.
- Diagnostics for count, duplicates, line lengths, encoding and control characters.
- No login automation, credential testing, or email-to-password lookup. The optional email field is only a local dataset label and is not sent anywhere.

## Run on Windows
From the repository root in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tools\passgan-local\setup.ps1
.\tools\passgan-local\run.ps1
```

The setup needs Git for Windows, Docker Desktop in Linux-container mode, and the pretrained checkpoint files. If your checkpoint already exists at `%USERPROFILE%\Downloads\PassGAN\PassGAN-master\pretrained`, the setup script attempts to copy it. Otherwise, put the required pretrained files into `tools\passgan-local\PassGAN\pretrained`. Required checkpoint files include `195000.ckpt.meta`, `195000.ckpt.index`, and the matching data shard.

Generated output:
`tools\passgan-local\PassGAN\generated_samples.txt`

Open the dashboard at the deployed static site or open `index.html` locally, then choose that output file to filter and export it. The web page does not pretend to run PassGAN in the browser.

## Safety and limitations
Use generated samples only for authorized password-strength research on systems and data you own or have explicit permission to test. A generated string is a guess, not proof of an account password. This project does not attempt sign-ins or test guesses against Gmail or other services.

The upstream PassGAN code and TensorFlow 1.4.1 are legacy research software. Keep the container isolated, do not expose it as a web service, and do not mount unrelated files or secrets into it.

## Project links
- [PassGAN local engine](tools/passgan-local/README.md)
- [Upstream PassGAN research repository](https://github.com/brannondorsey/PassGAN)
