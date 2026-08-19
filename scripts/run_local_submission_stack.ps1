param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($RepositoryRoot)
Set-Location -LiteralPath $root

foreach ($line in Get-Content -LiteralPath (Join-Path $root "deploy/.env")) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
        continue
    }
    $parts = $trimmed.Split("=", 2)
    $value = $parts[1].Trim()
    if (
        ($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))
    ) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $value, "Process")
}

$secretBytes = New-Object byte[] 48
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($secretBytes)
$random.Dispose()
$visionSecret = [Convert]::ToBase64String($secretBytes)

$env:VISION_STREAM_TOKEN_SECRET = $visionSecret
$env:KIOSK_CORS_ORIGINS = "http://127.0.0.1:15173"
$env:VISION_GATEWAY_ALLOWED_ORIGINS = "http://127.0.0.1:15173"
$env:VISION_EXPRESSION_MODE = "disabled"
$env:VISION_EYE_WORKER_URL = "http://127.0.0.1:8766"
$env:CENTRAL_AI_PROVIDER = "openai_luna"
$env:CENTRAL_AI_MODEL_ID = "gpt-5.6-luna"
$env:CENTRAL_AI_MODEL_REVISION = "gpt-5.6-luna"
$env:CENTRAL_AI_REASONING_EFFORT = "max"
$env:CENTRAL_AI_REASONING_CONTEXT = "current_turn"
$env:CENTRAL_AI_INPUT_VARIANT = "C"
$env:CENTRAL_AI_PROMPT_VERSION = "central-recommender-ko-v6"
[Environment]::SetEnvironmentVariable("RECOMMENDATION_CATALOG_PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("RECOMMENDATION_MATCHING_CATALOG_PATH", $null, "Process")

$python = (Resolve-Path -LiteralPath "apps/api/.venv/Scripts/python.exe").Path
$api = Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "apps.api.app.main:app",
    "--host", "127.0.0.1", "--port", "18000", "--workers", "1"
) -WorkingDirectory $root -WindowStyle Hidden -PassThru
$gateway = Start-Process -FilePath $python -ArgumentList @(
    "-m", "uvicorn", "apps.vision_gateway.local_server:app",
    "--host", "127.0.0.1", "--port", "18765", "--workers", "1"
) -WorkingDirectory $root -WindowStyle Hidden -PassThru

$env:VITE_USE_MOCK_API = "false"
$env:VITE_VISION_MODE = "live"
$env:VITE_VISION_TOKEN_MODE = "backend"
$env:VITE_VISION_TOKEN_URL = "http://127.0.0.1:18000/api/v1/sessions/{session_id}/vision-stream-token"
$env:VITE_VISION_GATEWAY_WS_URL = "ws://127.0.0.1:18765/vision/v1/stream"
$env:VITE_API_BASE_URL = "http://127.0.0.1:18000"
$env:VITE_LOOKBOOK_ID = "mcm-lookbook-v2"
$env:VITE_LOOKBOOK_VIDEO_URL = "/media/mcm-lookbook-v2.mp4"
$node = "C:/Program Files/nodejs/node.exe"
$vite = (Resolve-Path -LiteralPath "node_modules/vite/bin/vite.js").Path
$quotedVite = '"' + $vite + '"'
$kiosk = Start-Process -FilePath $node -ArgumentList @(
    $quotedVite, "--host", "127.0.0.1", "--port", "15173", "--strictPort"
) -WorkingDirectory (Join-Path $root "apps/kiosk") -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 3
$commandLeak = $false
foreach ($pidValue in @($api.Id, $gateway.Id, $kiosk.Id)) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $pidValue) -ErrorAction SilentlyContinue
    if ($process.CommandLine -and $process.CommandLine.Contains($visionSecret)) {
        $commandLeak = $true
    }
}

$fileLeak = $false
$textExtensions = @(".conf", ".example", ".json", ".md", ".ps1", ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml")
$files = Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue | Where-Object {
    $textExtensions -contains $_.Extension -and
    $_.FullName -notmatch "\\.git\\|\\node_modules\\|\\.venv\\|\\dist\\|\\.pytest_cache\\"
}
foreach ($file in $files) {
    try {
        if ([System.IO.File]::ReadAllText($file.FullName).Contains($visionSecret)) {
            $fileLeak = $true
            break
        }
    }
    catch {
        continue
    }
}

Write-Output ("api_started_pid=" + $api.Id)
Write-Output ("gateway_started_pid=" + $gateway.Id)
Write-Output ("kiosk_started_pid=" + $kiosk.Id)
Write-Output ("temporary_secret_command_line=" + $(if ($commandLeak) { "found" } else { "not_found" }))
Write-Output ("temporary_secret_files=" + $(if ($fileLeak) { "found" } else { "not_found" }))

$visionSecret = $null
[Array]::Clear($secretBytes, 0, $secretBytes.Length)
