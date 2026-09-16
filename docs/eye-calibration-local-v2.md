# Local eye calibration v2

This document defines the local browser-to-Eye-worker calibration path. It is
for the kiosk's webcam demo; it does not claim pixel-accurate eye tracking or
replace a dedicated infrared eye tracker.

## Required behaviour

1. Before training, the worker checks that a face is present, both eyes are
   visible, the face is centred and at an acceptable relative size, and the
   head is approximately forward. The boolean-only state must remain stable
   for one second. Face geometry and landmarks never leave the worker.
2. The worker chooses the next target. After the browser has painted that
   target, it attaches `calibration_id`, `target_id`, and
   `presented_at_mono_ms` to every camera frame. Only frames matching the
   current target and presentation interval may become training data.
3. The calibration queue is bounded to four frames. Old frames are discarded,
   and a frame delayed by more than 250 ms at the worker is not labelled.
4. The default `adaptive-dense5-v2` profile trains on 25 points and validates
   with eight independent points. Each target needs at least 15 valid samples
   over at least 500 ms. The worker advances the target, not a browser timer.
5. A local spatial error can trigger at most four targeted repair captures.
   A fresh eight-point verification follows every repair. A global signal
   failure, insufficient samples, cancellation, or a failed verification is
   fail-closed: the fitted model is discarded and the kiosk asks for a new
   calibration.

## Quality policy and diagnostics

`webcam-relaxed-v1` requires a session valid ratio of at least 85%, normalized
diagonal p50 error at most 15%, and p95 at most 30%. Every validation point
also requires at least 15 samples, a 70% valid ratio, p50 at most 25%, and p95
at most 40%.

The transient calibration summary may contain only aggregate counts and
normalized p50/p95 errors: face/eye detection failure causes, total and valid
sample counts, repair count, elapsed time, and quality checks. It must not
contain a camera frame, image bytes, landmark coordinates, raw gaze samples,
or a user identifier. The summary and fitted model are discarded when the
session ends, a new calibration begins, or the worker exits.

## Local verification

Run the four terminal processes described in
[`apps/kiosk/DEMO_3C_REAL_CAMERA_SMOKE.md`](../apps/kiosk/DEMO_3C_REAL_CAMERA_SMOKE.md).
Use a `VISION_STREAM_TOKEN_SECRET` of 32 bytes or more and restart Eye and the
Gateway after source changes.

After a calibration attempt, inspect only the aggregate diagnostic endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/internal/eye/v1/calibration-summary
```

Automated checks validate marker matching, queue eviction, face-position
gating, repair followed by independent verification, cancellation, and the
absence of raw geometry in progress messages. They do not measure real-camera
accuracy; that requires repeated manual trials across the intended cameras,
lighting, distances, and users.
