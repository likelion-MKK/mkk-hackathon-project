# Demo 3-C actual-camera smoke (local test only)

This is a reproducible **manual** acceptance run for the browser's physical
camera. It is not a production release gate: ADR-0001 remains Proposed, and
the run must never be reported as successful if the physical device, browser
permission, Eye calibration, or Gateway cannot complete.

The test process is disposable and loopback-only:

```text
Kiosk → browser getUserMedia → EyeTrax worker → Vision Gateway
      → API observation ingest → demo static AOI → Variant C
      → DeterministicCentralStub Top 1
```

It does not use Luna, Supabase, a fake media device, or a production provider.
Do not add `--use-fake-device-for-media-stream` or a staged camera video to
any command below.

## Preconditions

- The canonical file is staged at `apps/kiosk/public/media/mcm-lookbook-v2.mp4`.
  Verify its declared 33.5s / 1280×720 / 24fps identity before the run.
- An actual camera is visible to Windows and a browser is allowed to prompt for
  it. The smoke operator must grant the browser's camera prompt; do not bypass
  it with a Chromium fake-device flag.
- The EyeTrax runtime is Python 3.12.10 and has a verified
  `face_landmarker.task` at `services/eye/.cache/face_landmarker.task`.
- Use a terminal process with no `DATABASE_URL`, `CENTRAL_AI_ENDPOINT`, or
  `CENTRAL_AI_PROVIDER=openai_luna`. The Demo 3-C API factory rejects those
  values before it starts.

## Start the disposable local services

Set a shared, local-only `VISION_STREAM_TOKEN_SECRET` in the API and Gateway
terminal sessions. Keep the value out of the repository, logs, screenshots,
and command history. The commands below deliberately require you to provide
the same value in both sessions rather than writing it to a file.

### 1. API test instance

```powershell
$env:MCM_LOOKBOOK_DEMO_STATIC_AOI = "1"
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:CENTRAL_AI_ENDPOINT -ErrorAction SilentlyContinue
Remove-Item Env:CENTRAL_AI_PROVIDER -ErrorAction SilentlyContinue
$env:VISION_STREAM_TOKEN_SECRET = "<same local-only secret used by Gateway>"
uv run --project apps/api --locked python -m uvicorn `
  apps.api.app.demo_3c_test_app:create_demo_3c_test_app --factory `
  --host 127.0.0.1 --port 8000
```

The explicit `--factory` is required. This factory injects
`DeterministicCentralStub`; it cannot be enabled by a production provider
environment variable.

### 2. Eye worker

```powershell
$env:EYE_FACE_MODEL_PATH = (Resolve-Path "services/eye/.cache/face_landmarker.task").Path
uv run --project services/eye --locked python services/eye/scripts/run_worker.py
```

### 3. Vision Gateway

```powershell
$env:VISION_STREAM_TOKEN_SECRET = "<the same local-only secret>"
$env:VISION_EYE_WORKER_URL = "http://127.0.0.1:8766"
$env:VISION_EXPRESSION_MODE = "disabled"
uv run --project apps/api --locked python -m uvicorn `
  apps.vision_gateway.local_server:app --host 127.0.0.1 --port 8765
```

### 4. Kiosk browser

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_VISION_MODE = "live"
$env:VITE_VISION_GATEWAY_WS_URL = "ws://127.0.0.1:8765/vision/v1/stream"
$env:VITE_VISION_TOKEN_URL = "http://127.0.0.1:8000/api/v1/sessions/{session_id}/vision-stream-token"
$env:VITE_VISION_TOKEN_MODE = "backend"
npm run dev:kiosk
```

Open the printed local URL in a browser, consent, and grant camera access. The
original full-viewport Dense5 calibration moves through 25 training points and
8 validation points. One attempt has 64 seconds of planned capture time; one
full retry has 128 seconds of capture plus local processing overhead. If the
Eye worker is unavailable, calibration must stop with an error; do not
continue by inventing a gaze point.

## Success procedure

1. Start the 33.5-second `mcm-lookbook-v2` and, during `[5000,12000)`, look at
   the top-left Toni region. Keep the browser video fully visible so that this
   is video content rather than letterbox/pillarbox.
2. Let the lookbook end. The Kiosk posts gaze-only v2 observations and calls
   `/complete` once; it never sends browser product candidates.
3. Poll `GET /api/v2/sessions/{session_id}/recommendation` until it returns
   `200`. A real-camera pass requires all of the following:

   - `status=completed` and `selected_product_id=mcm-toni-medium-disco-visetos`;
   - `data_quality.gaze_valid_ratio > 0` and an evidence reference of
     `kind=window` for the Toni product;
   - the deterministic test-only provider is the only provider running;
   - the static AOI match is the Toni `whole_product` component with
     `monogram`, `shopper`, and `tote` tags;
   - Variant C has `timeline=null` and no frame ID, capture time, screen/video
     coordinate, raw gaze, or token; and
   - every submitted observation has `expression=null` and
     `expression_reason=not_observed`.

The response intentionally exposes aggregate quality ratios rather than raw
gaze or per-frame records. `matched_frame_ratio` measures gaze+Face
co-occurrence and therefore remains `0` in this gaze-only Demo 3-C. A completed
Toni result with a positive gaze ratio and Toni window evidence is the
privacy-safe check that at least one valid gaze and AOI match reached the
test-only provider.

## Required fail-closed checks

No case below may yield `completed`, a neutral coordinate, nearest product, or
an arbitrary product ID. No case may send Luna, write raw media/gaze/token, or
retain a Variant C timeline.

| Case | Expected result | Automated coverage |
| --- | --- | --- |
| Browser camera permission denied | Camera error UI; no stream/complete | `apps/kiosk/src/camera/FrameSource.test.ts` |
| Camera unavailable | Camera error UI; tracks released | `apps/kiosk/src/camera/FrameSource.test.ts` |
| Eye worker unavailable / gaze unavailable | Calibration fails or gaze is null with its reason | `tests/integration/test_vision_stream_gateway.py` |
| Frame ID, sequence, video ID, video time, or epoch mismatch | Gateway drops the derived gaze or errors safely | `test_eye_worker_result_must_preserve_each_frame_context_field` |
| Letterbox/pillarbox or video-outside coordinate | No attention / no AOI candidate | `apps/kiosk/src/app/reaction-batch.test.ts` |
| AOI-outside coordinate | `no_aoi_match`, no eligible product | `apps/api/tests/test_v2_lookbook_demo_static_assumptions.py` |
| Static opt-in absent / pending metadata | `409 aoi_metadata_unapproved` | `test_demo_3c_default_pending_metadata_fail_closed` |
| Gateway disconnect | In-flight frame is rejected; playback cannot complete analysis | `apps/kiosk/src/clients/vision/LocalVisionStreamClient.test.ts` |
| Browser product candidate | Kiosk batch keeps `candidates=[]` | `apps/kiosk/src/app/observation-batch-v2.test.ts` |

Stop any one of the API, Eye worker, or Gateway processes for the relevant
failure case. Then restart the whole disposable stack for the next run rather
than reusing the interrupted session.
