param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($RepositoryRoot)
Set-Location -LiteralPath $root

# Reuse only the existing provider credential; local runs do not connect to the DB.
if (-not $env:OPENAI_API_KEY) {
    foreach ($line in Get-Content -LiteralPath (Join-Path $root "deploy/.env")) {
        if ($line -notmatch '^\s*OPENAI_API_KEY\s*=') { continue }
        $value = $line.Substring($line.IndexOf("=") + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $env:OPENAI_API_KEY = $value
        $value = $null
    }
}
if (-not $env:OPENAI_API_KEY) { throw "An existing OPENAI_API_KEY is required." }

foreach ($name in @(
    "DATABASE_URL", "CENTRAL_AI_ENDPOINT", "MCM_LOCAL_DEMO_MODE",
    "MCM_LOCAL_DEMO_ALLOW_INSUFFICIENT_SIGNAL", "MCM_LOOKBOOK_DEMO_STATIC_AOI"
)) { [Environment]::SetEnvironmentVariable($name, $null, "Process") }

$env:KIOSK_CORS_ORIGINS = "http://127.0.0.1:15173"
$env:VISION_GATEWAY_ALLOWED_ORIGINS = "http://127.0.0.1:15173"
$env:VISION_EXPRESSION_MODE = "disabled"
$env:VISION_EYE_WORKER_URL = "http://127.0.0.1:8766"
$env:EYE_WORKER_HOST = "127.0.0.1"
$env:EYE_WORKER_PORT = "8766"
$env:EYE_FACE_MODEL_PATH = Join-Path $root "services/eye/.cache/face_landmarker.task"
$env:CENTRAL_AI_PROVIDER = "openai_luna"
$env:CENTRAL_AI_MODEL_ID = "gpt-5.6-luna"
$env:CENTRAL_AI_MODEL_REVISION = "gpt-5.6-luna"
$env:CENTRAL_AI_REASONING_EFFORT = "medium"
$env:CENTRAL_AI_REASONING_CONTEXT = "current_turn"
$env:CENTRAL_AI_INPUT_VARIANT = "C"
$env:CENTRAL_AI_PROMPT_VERSION = "central-recommender-ko-v8"
$env:RECOMMENDATION_CATALOG_PATH = "data/products/mcm-submission-recommendation-profile-v4.json"
$env:RECOMMENDATION_MATCHING_CATALOG_PATH = "data/products/mcm-submission-matching-profiles-v4.json"

$env:VITE_USE_MOCK_API = "false"
$env:VITE_VISION_MODE = "live"
$env:VITE_CALIBRATION_PROFILE = "adaptive-dense5-v2"
$env:VITE_VISION_TOKEN_MODE = "backend"
$env:VITE_VISION_TOKEN_URL = "http://127.0.0.1:8000/api/v1/sessions/{session_id}/vision-stream-token"
$env:VITE_VISION_GATEWAY_WS_URL = "ws://127.0.0.1:8765/vision/v1/stream"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_API_PROXY_TARGET = ""
$env:VITE_LOOKBOOK_ID = "mcm-lookbook-v2"
$env:VITE_LOOKBOOK_VIDEO_URL = "/media/mcm-lookbook-v2.mp4"
$env:VITE_KIOSK_DEBUG_AOI = "false"

$python = (Resolve-Path -LiteralPath "apps/api/.venv/Scripts/python.exe").Path
$eyePython = (Resolve-Path -LiteralPath "services/eye/.venv/Scripts/python.exe").Path
$bundledNode = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
$node = if (Test-Path -LiteralPath $bundledNode) { $bundledNode } else { (Get-Command node.exe).Source }
$vite = (Resolve-Path -LiteralPath "node_modules/vite/bin/vite.js").Path
if (-not (Test-Path -LiteralPath $env:EYE_FACE_MODEL_PATH)) { throw "The local Eye face model is missing." }

# Validate configuration without sending an API request.
$preflight = 'from apps.api.app.main import app; from apps.api.app.v2_central import OpenAILunaCentralClient, _load_luna_prompt; assert isinstance(app.state.central_client, OpenAILunaCentralClient); assert not app.state.v2_store.durable_mode; assert len(app.state.v2_store.list_products()) == 10; _load_luna_prompt(); print("local_config=ready provider=Luna effort=medium prompt=v8 catalog=10")'
& $python -c $preflight
if ($LASTEXITCODE -ne 0) { throw "Local Luna configuration validation failed." }
if ($ValidateOnly) { return }

# Do not terminate an unknown listener when switching from the camera-test stack.
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
foreach ($port in @(8000, 8765, 8766, 15173)) {
    if ($listeners.Port -contains $port) { throw "Port $port is already in use; stop its existing local stack first." }
}

$secretBytes = New-Object byte[] 48
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($secretBytes)
$random.Dispose()
$env:VISION_STREAM_TOKEN_SECRET = [Convert]::ToBase64String($secretBytes)
[Array]::Clear($secretBytes, 0, $secretBytes.Length)
$logRoot = Join-Path $root ("tmp/local-luna-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$started = @()
try {
    $eye = Start-Process -FilePath $eyePython -ArgumentList @(
        ('"' + (Join-Path $root "services/eye/scripts/run_worker.py") + '"')
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "eye.out.log") -RedirectStandardError (Join-Path $logRoot "eye.err.log")
    $started += $eye
    $api = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "apps.api.app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-access-log"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "api.out.log") -RedirectStandardError (Join-Path $logRoot "api.err.log")
    $started += $api
    $gateway = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "apps.vision_gateway.local_server:app", "--host", "127.0.0.1", "--port", "8765", "--workers", "1", "--no-access-log"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "gateway.out.log") -RedirectStandardError (Join-Path $logRoot "gateway.err.log")
    $started += $gateway
    $kiosk = Start-Process -FilePath $node -ArgumentList @(
        ('"' + $vite + '"'), "--host", "127.0.0.1", "--port", "15173", "--strictPort"
    ) -WorkingDirectory (Join-Path $root "apps/kiosk") -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "kiosk.out.log") -RedirectStandardError (Join-Path $logRoot "kiosk.err.log")
    $started += $kiosk
    Write-Output ("local_url=http://127.0.0.1:15173/ api_pid=" + $api.Id + " gateway_pid=" + $gateway.Id + " eye_pid=" + $eye.Id + " kiosk_pid=" + $kiosk.Id)
    Write-Output ("logs=" + $logRoot)
    # Keep the launcher alive; stop helpers when one exits or the launcher stops.
    while (-not ($started | Where-Object HasExited)) { Start-Sleep -Seconds 1 }
} finally {
    foreach ($process in $started) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
    [Environment]::SetEnvironmentVariable("VISION_STREAM_TOKEN_SECRET", $null, "Process")
}
