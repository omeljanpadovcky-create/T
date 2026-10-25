$ErrorActionPreference = "Stop"

param(
    [string]$Path = (Join-Path $PSScriptRoot "PassGAN\generated_samples.txt")
)

if (-not (Test-Path -LiteralPath $Path)) {
    throw "Sample file not found: $Path"
}

$bytes = [System.IO.File]::ReadAllBytes($Path)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$lines = @($text -split "\r?\n" | Where-Object { $_.Length -gt 0 })
$nonAsciiBytes = @($bytes | Where-Object { $_ -gt 127 }).Count
$uniqueLines = @($lines | Sort-Object -Unique)
$nonAsciiLines = @($lines | Where-Object { $_ -match "[^\x00-\x7F]" })
$controlLines = @($lines | Where-Object { $_ -match "[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]" })
$lengths = @($lines | ForEach-Object { $_.Length } | Sort-Object)

Write-Host ""
Write-Host "PassGAN sample report" -ForegroundColor Cyan
Write-Host "---------------------"
Write-Host ("File:             {0}" -f (Resolve-Path -LiteralPath $Path))
Write-Host ("Bytes:            {0}" -f $bytes.Length)
Write-Host ("Non-ASCII bytes:  {0}" -f $nonAsciiBytes)
Write-Host ("Non-empty lines:  {0}" -f $lines.Count)
Write-Host ("Unique lines:     {0}" -f $uniqueLines.Count)
Write-Host ("Duplicate lines:  {0}" -f ($lines.Count - $uniqueLines.Count))
Write-Host ("Non-ASCII lines:  {0}" -f $nonAsciiLines.Count)
Write-Host ("Control-char lines: {0}" -f $controlLines.Count)

if ($lines.Count -gt 0) {
    Write-Host ("Shortest line:    {0} chars" -f $lengths[0])
    Write-Host ("Longest line:     {0} chars" -f $lengths[-1])
}

if ($nonAsciiLines.Count -gt 0) {
    Write-Host ""
    Write-Host "Examples containing non-ASCII characters (first 10):"
    $nonAsciiLines | Select-Object -First 10 | ForEach-Object { Write-Host ("  " + $_) }
}

if ($controlLines.Count -gt 0) {
    Write-Warning "Control characters were detected. Inspect the source encoding before interpreting these samples."
} elseif ($nonAsciiLines.Count -gt 0) {
    Write-Warning "Non-ASCII characters exist in the decoded output. This may be model vocabulary or encoding behavior; it is not automatically proof of corruption."
} else {
    Write-Host "All sample characters are ASCII." -ForegroundColor Green
}

Write-Host ""
Write-Host "Note: sample statistics do not measure real-world password strength or prove model quality."
