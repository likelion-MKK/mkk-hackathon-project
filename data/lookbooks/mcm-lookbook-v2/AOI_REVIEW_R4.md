# MCM Lookbook v2 AOI R4 review

## 상태

- 새 metadata revision: `mcm-lookbook-v2-aoi-r4-pending-2026-08-18`
- metadata 파일: [`aoi-metadata-v2-r4-pending.json`](./aoi-metadata-v2-r4-pending.json)
- proposal: [`aoi-proposal-2026-08-18-r4.json`](./aoi-proposal-2026-08-18-r4.json)
- approval status: `pending_review` (exposures 0개)
- 검수일: `2026-08-18`
- 영상 관찰·proposal 작성: Codex. 이는 사람 owner 검수나 sign-off가 아니다.
- R4 owner reviewer / sign-off: **미기록**

기존 [`aoi-metadata-v2-r3-approved.json`](./aoi-metadata-v2-r3-approved.json)의
양유상 sign-off는 Toni top-left 한 개의 Vision 3-B demo 범위다. production calibration이나
R4 전체를 승인한 기록이 아니므로, R4 approved metadata는 만들지 않았다.

## 검수한 영상과 identity

검수 대상은 Desktop 원본 `C:\Users\andyw\Desktop\mcm 동영상.mp4`와 Kiosk 사본
`apps/kiosk/public/media/mcm-lookbook-v2.mp4`이다. 두 파일은 아래 identity가 서로 같고
기존 metadata와도 일치했다.

| 항목 | 값 |
| --- | --- |
| video_id / manifest | `mcm-lookbook-v2` / `mcm-lookbook-v2-2026-08-18` |
| SHA-256 | `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89` |
| byte length | `5,754,164` |
| duration | `33,500ms` |
| resolution / FPS | `1280×720 / 24FPS` |

임시 검수 frame은 저장소, Git, metadata, 로그, DB 또는 test artifact에 남기지 않았다.

## 실제 영상 관찰 결과

| 실제 구간 | 장면 | R4 처리 |
| --- | --- | --- |
| `[5000, 12958)` | 2×2 shopper grid | R3에서 사람 검수한 top-left만 proposal 후보로 보존한다. `[12000,12958)` tail은 새 owner 결정이 없어 미매핑이다. |
| `[12958, 12959)` | hard-cut 경계 | 1ms guard band로 미매핑한다. |
| `[12959, 20958)` | Boston-shaped bag / flap bag / zip pouch / backpack의 정적 2×2 grid | 실제 상품은 보이지만 R4 owner가 exact catalog ID를 확인하지 않았다. product ID·polygon·AOI를 추정하지 않고 모두 pending으로 둔다. |
| `[20958, 28000)` | 이동 모델 장면 | 실제 이동 시작은 약 `20958.3ms`다. 요청한 21~28초 이동 장면 전체를 매핑하지 않는다. |

`[0,5000)` intro/title과 `[28000,33500)` closing도 매핑하지 않는다. 시간은
`[start_ms,end_ms)` 반개구간이며, 구간을 연속 매핑으로 억지로 채우지 않았다.

## Whole-product proposal

아래는 새 R4 승인 exposure가 아니라, 실제 정적 화면과 R3 사람 승인 값을 대조해 보존한
후보 하나다. 손잡이·스트랩·로고·하드웨어·잠금장치 등 detail component는 작성하지 않았다.

| 항목 | 값 |
| --- | --- |
| proposal ID | `proposal-r4-preserve-r3-toni-grid-top-left` |
| AOI ID | `mcm-lookbook-v2-toni-grid-top-left` |
| product_id | `mcm-toni-medium-disco-visetos` |
| start_ms / end_ms | `5000` / `12000` |
| polygon (`video_normalized`) | `[[0.08,0.02],[0.42,0.02],[0.42,0.49],[0.08,0.49]]` |
| component_code | `whole_product` |
| parent_aoi_id / specificity_rank | `null` / `0` |
| controlled visual tags | `monogram`, `shopper`, `tote` |
| 실제 checkpoint | `5000`, `8500`, `11000`ms |
| 다른 product_id와의 겹침 | R4에는 다른 exposure를 제안하지 않았다. 화면상 top-left cell 안에 보존 polygon이 있고 인접 product는 바깥이다. 사람 owner가 최종 non-overlap을 수용하기 전까지 pending이다. |

이 후보의 좌표·시간·product ID·tags는 R3에서 임의로 바꾸지 않았다. 실제 첫 grid가
`12000ms` 뒤에도 정적이라는 관찰은 기록하되, R3 sign-off 범위를 Codex가 확장하지 않았다.

## Margin 상태

R3에서 보존한 whole-product polygon은 normalized `0.04` provisional margin이 반영된 값으로
기록되어 있다. canonical 1280×720 기준으로 가로 `51.2px`, 세로 `28.8px`에 해당한다.
이는 production calibration 결과가 아니며 R4 owner acceptance도 아직 없다. production 승인 전에는
`1.5 × calibration-error P95`로 바꾸고, same-product containment와 다른 product ID의 overlap을
다시 검수해야 한다. 이번 R4에는 component AOI가 없으므로 margin을 상속받는 세부 영역도 없다.

## 사람 owner sign-off worksheet

아래 다섯 값이 모두 채워지기 전에는 `approval_status`를 `approved`로 바꾸거나
`aoi-metadata-v2-r4-approved.json`을 만들면 안 된다.

| 필수 값 | R4 현재 값 |
| --- | --- |
| reviewer_name | 미기록 |
| reviewed_on | 미기록 |
| decision | 미기록 (`approve_selected_exposures` 또는 `reject_and_request_redraw`) |
| selected exposure | 미기록 |
| provisional 0.04 margin 수용 여부 | 미기록 |

선택한 exposure마다 exact catalog product ID, `[start_ms,end_ms)`, polygon,
`whole_product`, controlled tags 및 다른 product ID와의 non-overlap을 다시 확인해야 한다.

## 다음 단계와 제외 범위

- 아직 미검수: 첫 grid의 R3 범위 밖 tail과 나머지 세 cell, 두 번째 정적 grid의 네 상품 모두.
- 21~28초 이동 장면은 이번 배포용 mapping에서 제외했다.
- handle, strap, logo, hardware, closure 등 detail component AOI는 배포 후 calibration 기반 후속 작업이다.
- R4 approved metadata가 실제 사람 sign-off 후 만들어진 경우에만 `valid gaze → capture-time video_time_ms → video_normalized 좌표 → whole_product AOI → 정확한 product_id → whole_product/tag aggregate → RecommendationEvidence → variant C payload` 전체 Vision 3-B를 별도 재검증한다.
- 이 R4 pending revision만으로는 배포 approved 상태나 Vision 전체 완료를 주장하지 않는다.
