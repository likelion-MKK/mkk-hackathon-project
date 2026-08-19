$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputPath = Join-Path $repositoryRoot "artifacts\recommendation\openai-luna-max\diagnostic-full-v4-no-timeout.json"
$secureKey = Read-Host "Enter OPENAI_API_KEY" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

Push-Location $repositoryRoot
try {
    $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    uv run --with-requirements requirements-openai-benchmark.txt python experiments/recommendation/openai_benchmark.py diagnostic-full `
        --live `
        --synthetic-only `
        --budget-usd 5 `
        --no-timeout `
        --output $outputPath
    if ($LASTEXITCODE -ne 0) {
        throw "Luna v4 diagnostic failed with exit code $LASTEXITCODE."
    }
    Write-Host "Completed: $outputPath" -ForegroundColor Green
}
finally {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    Pop-Location
}
