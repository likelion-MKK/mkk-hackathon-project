# MCM Lookbook v2 AOI human-review handoff

> **Superseded review draft:** owner 검수는 [`AOI_REVIEW_R3.md`](./AOI_REVIEW_R3.md)와
> [`aoi-proposal-2026-08-18-r3.json`](./aoi-proposal-2026-08-18-r3.json)을 사용한다.
> 이 문서는 r2의 역사적 handoff를 보존하기 위한 기록이며 production metadata로
> 사용하지 않는다.

## Status

This is a human-review handoff record, not production AOI metadata.  The
canonical `aoi-metadata-v2.json` remains `pending_review` with no exposures.
It must not be changed to `approved` until a named reviewer verifies each
product ID, time interval, polygon, component, and controlled tag below.

No raw frame, gaze coordinate, calibration sample, token, or customer data is
stored in this record.

## Verified media identity

| Field | Verified value |
| --- | --- |
| Video ID | `mcm-lookbook-v2` |
| Manifest version | `mcm-lookbook-v2-2026-08-18` |
| Duration | `33500` ms |
| Resolution / FPS | `1280x720` / `24` |
| Byte length | `5754164` |
| SHA-256 | `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89` |

On 2026-08-18, the Desktop source and the Kiosk media copy were checked with
`apps.api.scripts.verify_lookbook_media`; both matched this identity exactly.

## Replay spot-checks (not annotations)

These are navigation anchors from local playback only.  They deliberately do
not assign a catalog product ID, component, tag, polygon, or exposure range.
They are not sufficient evidence to approve AOI metadata.

| Approximate media time | Observed visual state | AOI mapping status |
| --- | --- | --- |
| `~1000` ms | Intro/title card | No product AOI |
| `~10400` ms | Four-product grid | Requires product identity review |
| `~13000` ms | Four-bag grid begins: Boston bag, structured flap bag, zip pouch, backpack | Candidate whole-product and visible-component review required |
| `~17000` ms | Stable four-bag grid with mixed silhouettes and visible handles, straps, closures, pockets and logo hardware | Candidate whole-product and visible-component review required |
| `~21000` ms | Cut from four-bag grid to two-model carrying scene | No grid AOI after this boundary |
| `~23400` ms | Two-model carrying scene | Requires product identity and polygon review |
| `~30600` ms | Closing analysis card | No product AOI |

## Provisional mapping proposal (awaiting approval)

The candidate time ranges, product links, normalized polygons and margin policy
are now recorded in
[`aoi-proposal-2026-08-18.json`](./aoi-proposal-2026-08-18.json). It is a
non-production review artifact: the Backend must continue to use the empty
pending metadata until a reviewer approves a new revision.

- Proposed stable intervals only: `[5000, 12000)`, `[13000, 21000)`, and
  `[22000, 28000)`. The four-bag grid begins at `13000` ms, not `14000` ms.
- Proposed catalog candidates: Toni grid/model totes, Ella Boston grid item,
  and Aren Nova backpack grid item. The Ella proposal now includes its visible
  handle, left/right detachable-strap, and charm/trim candidates; the backpack
  proposal includes its visible handle, front pocket, and logo-plaque
  candidates.
- The top-right structured flap bag and bottom-left zip pouch each have a
  non-production visual-component inventory (strap/closure/hardware and
  closure/trim respectively). They remain deliberately unmapped because their
  exact canonical catalog IDs are not yet established.
- Whole-product polygons include a provisional `0.04` normalized margin
  (`51.2px` horizontally and `28.8px` vertically at 1280×720). Visible
  component-core polygons use zero expansion and must not inherit that margin.
- Before 3-B, replace that margin with `1.5 × calibration-error P95` and
  recheck that differently mapped products do not overlap.

## Required human annotation worksheet

Review the complete half-open video range `[0, 33500)` and fill only ranges
that a reviewer can verify.  Leave uncertain ranges unannotated; do not use a
nearest-looking catalog item as a substitute.

| Review interval | Human reviewer | Product ID | `whole_product` polygon | Optional component polygons | Controlled tags | Review result |
| --- | --- | --- | --- | --- | --- | --- |
| `[0, 3500)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[3500, 7000)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[7000, 10500)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[10500, 13000)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[13000, 17000)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[17000, 21000)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[21000, 24500)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[24500, 28000)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[28000, 31500)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |
| `[31500, 33500)` | unassigned | unassigned | unassigned | unassigned | unassigned | pending |

For every approved exposure, the reviewer must verify all of the following
before it is copied into `aoi-metadata-v2.json`:

1. The exact `product_id` exists in
   `data/products/mcm-demo-recommendation-profile-v2.json` and refers to the
   item visibly shown in the video.
2. The half-open `[start_ms, end_ms)` interval shows that same item.
3. The polygon uses `video_normalized` coordinates and does not include a
   different product.  For a moving item, split the time range instead of
   creating one large polygon.
4. A parent `whole_product` AOI has `parent_aoi_id: null` and
   `specificity_rank: 0`.  A component AOI points only to the same product's
   parent, has a larger rank, and is contained in the parent's time range.
5. `component_code` is one of the AOI contract's allowlisted values and every
   visual tag belongs to that exact product's `controlled_tags`.
6. Same-product overlaps are retained.  Different-product overlaps are also
   retained in metadata so the Backend can fail closed as `ambiguous_product`.

## Gaze-tolerance margin decision

No calibration aggregate is available yet.  Whole-product polygons in the
proposal use a `0.04` normalized temporary margin. Before 3-B, replace it with
`1.5 x` the measured 95th-percentile calibration error and rerun overlap
checks. Component AOIs use an explicit `0.00` expansion: they identify only a
visible core and must be re-inspected after calibration rather than widened
automatically. Omit an unclear component rather than guessing its boundary.

## Current blockers

- `data/products/submissions/` contains only its README and template; it has
  no reviewed per-product submission that can corroborate a visual catalog-ID
  mapping.
- No actual human reviewer, annotation decision, or calibration aggregate was
  supplied for this revision.
- An automated replay check cannot certify the human-review condition required
  for `approval_status: approved`.

## Next action

An authorized reviewer should complete this worksheet from the canonical
source video, then create a new metadata revision with only verified
exposures.  Run `test_v2_aoi.py` including the existing pending fixture first;
after approval, run the separate 3-B evidence mapping test before calling the
Vision pipeline product-aware.
