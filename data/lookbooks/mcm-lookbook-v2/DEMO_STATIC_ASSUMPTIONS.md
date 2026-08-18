# MCM Lookbook v2 — demo-only static AOI assumptions

## Scope and activation boundary

`aoi-metadata-v2-demo-static-assumptions.json` is an explicitly injected,
non-production demo fixture.  Its `approved` schema value permits the existing
Backend AOI mapper to exercise the static demo; it is **not** human approval of
the product identity or a production activation.

- The canonical `aoi-metadata-v2.json` remains `pending_review` with zero
  exposures.
- The normal Backend must continue to load that pending file.
- Only a test/demo bootstrap that explicitly passes this file may use it.
- The fixture contains no raw frame, gaze coordinate, token, or individual
  timeline.

For a local presentation server, set only this explicit opt-in flag before
starting the API:

```powershell
$env:MCM_LOOKBOOK_DEMO_STATIC_AOI = "1"
```

With the flag absent (the default), `configured_recommendation_repository()`
loads the canonical pending metadata. Never add this flag to deployment
environment files.

## Deliberate assumptions

All polygons are stable static-screen regions and include the existing demo
`0.04` normalized whole-product margin. The product mappings below are selected
from the current 10-product catalog so strict catalog validation still runs.
They are presentation assumptions, not claims that the video proves an exact
official SKU.

| Interval / zone | Demo catalog product ID | Why it is usable for the demo | Required correction before production |
| --- | --- | --- | --- |
| `[5000,12000)` 2x2 grid, all four cells | `mcm-toni-medium-disco-visetos` | The cells share the Toni shopper/tote family, monogram, handles, and plaque presentation. | Confirm the exact Toni size/colorway rather than treating the current medium Disco profile as a visual SKU match. |
| `[13000,21000)` top-left Boston | `mcm-ella-small-disco-visetos` | Boston silhouette, top handles, monogram and hanging tag are present. | Confirm the exact Ella size/material/colorway. |
| `[13000,21000)` top-right structured shoulder bag | `mcm-aren-east-west-shoulder-visetos` | This is a temporary catalog-shape match only. | Resolve the visible lock-closure bag against its exact official product; do not present it as verified Aren East-West. |
| `[13000,21000)` bottom-left zip pouch | `mcm-pina-vanity-case-studded-calfskin` | This is a temporary compact structured-bag placeholder only. | Replace with the exact pouch/phone-pouch catalog record; no material or monogram claim is carried into its tags. |
| `[13000,21000)` bottom-right backpack | `mcm-stark-side-studs-backpack-gold-crystal-visetos` | The visible backpack family and monogram presentation are close enough for a controlled demo mapping. | Confirm exact Stark/Aren family, size, colorway and material. |

No AOI is supplied for transitions or the `[22000,28000)` moving-model scene.
An unmapped or overlapping coordinate must still fail closed; this fixture does
not add nearest-product fallback behavior.

## Margin decision and exit criteria

`0.04` normalized is accepted only for this local/demo fixture. It is not a
production calibration result. Before production activation, replace it with
`1.5 × calibration-error P95`, confirm every product ID against its official
source, redraw any changed AOI, and rerun different-product overlap tests.

## Demo 3-B completion boundary

`apps/api/tests/test_v2_lookbook_demo_3b.py` uses the explicit opt-in and the
public API boundary to verify this demo flow:

```text
synthetic valid gaze + capture-time video context
  → static demo AOI
  → aggregate Variant C evidence
  → deterministic test-only Top 1
```

It checks that the default path, without the opt-in flag, remains
`pending_review` and rejects the observation with
`aoi_metadata_unapproved` rather than attributing a product. The test double
receives no raw frame, screen/video coordinate, frame ID, capture time, token,
or timeline. This is a demo backend integration test, not a browser
camera/Eye/Gateway or production-Luna smoke test.
