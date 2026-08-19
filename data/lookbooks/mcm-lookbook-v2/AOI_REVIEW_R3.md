# MCM Lookbook v2 AOI owner-review pack

## 현재 상태

이 문서는 실제 영상과 현재 10개 상품 catalog를 대조한 **owner 검수 기록**이다.
양유상이 2026-08-18에 Toni top-left whole-product AOI 하나만 Vision 3-B demo
용으로 승인했다. 기존 `data/lookbooks/mcm-lookbook-v2/aoi-metadata-v2.json`은
계속 `pending_review`·exposures 0개로 보존한다. 기본 Backend 경로도 pending
metadata를 사용하며, 3-B는 별도 approved r3 revision을 명시적으로 주입해
검증한다.

최신 후보안은
[`aoi-proposal-2026-08-18-r3.json`](./aoi-proposal-2026-08-18-r3.json)이다.
이전 r2의 잘못되거나 과도한 후보는 그대로 production에 사용하지 않는다.

## Partial approval for Vision 3-B

| 항목 | 승인 기록 |
| --- | --- |
| 검수자 | 양유상 |
| 검수일 | `2026-08-18` |
| 결정 | `approve_selected_exposures` |
| 승인 metadata | `aoi-metadata-v2-r3-approved.json` |
| 승인 AOI | `mcm-lookbook-v2-toni-grid-top-left` |
| 상품 | `mcm-toni-medium-disco-visetos` |
| 시간 구간 | `[5000, 12000)` |
| polygon | `[[0.08,0.02],[0.42,0.02],[0.42,0.49],[0.08,0.49]]` |
| component / tags | `whole_product` / `monogram`, `shopper`, `tote` |
| checkpoint | `5000`, `8500`, `11000` ms 확인 |
| 다른 상품 겹침 | 없음 확인 |
| margin | demo 전용 `0.04` normalized 수용; production 전 `1.5 × calibration-error P95`로 교체 필요 |

이 승인에는 다른 Toni grid 세 칸, Ella, Aren backpack, 모든 component 후보,
unresolved region, moving scene이 포함되지 않는다.

## 검증된 영상 identity

| 항목 | 값 |
| --- | --- |
| Video ID | `mcm-lookbook-v2` |
| Manifest | `mcm-lookbook-v2-2026-08-18` |
| 길이 | `33,500ms` |
| 해상도 / FPS | `1280x720` / `24` |
| Byte length | `5,754,164` |
| SHA-256 | `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89` |

Desktop 원본과 Kiosk 사본은 동일 fingerprint·길이·해상도·FPS로 확인했다.
검수용 raw frame은 저장소·metadata·로그·DB에 넣지 않는다.

## 이번 검수에서 승인 후보로 잡은 범위

| 구간 | 위치 | 후보 product ID | 상태 |
| --- | --- | --- | --- |
| `[5000, 12000)` | 2x2 shopper grid 4칸 | `mcm-toni-medium-disco-visetos` 각 1개 | **top-left만 3-B 승인**, 나머지 세 칸은 pending |
| `[13000, 21000)` | 좌상단 Boston bag | `mcm-ella-small-disco-visetos` | 가장 명확한 3-B 최소 후보 |
| `[13000, 21000)` | 우하단 backpack | `mcm-aren-nova-medium-backpack-econyl` | Aren과 Stark 구별을 owner가 확인 |

각 whole-product polygon은 아이트래커 오차를 고려해 `0.04` normalized
margin을 포함한 넓은 사각형이다. 네 grid AOI와 13–21초의 좌상단/우하단 AOI는
서로 겹치지 않도록 간격을 남겼다. 경계와 transition은 어느 상품에도 귀속하지
않는다.

### 상품 식별 근거

- 5–12초 grid: 네 가방 모두 Visetos shopper/tote 실루엣, 두 top handle,
  양쪽 strap, 앞쪽 logo plaque가 반복된다. MCM Toni 공식 페이지도 Visetos
  shopper, top handle, logo brass plate, zip closure를 명시한다.
  [Toni 공식 PDP](https://us.mcmworldwide.com/en_US/women/bags/totes-shoppers/toni-top-zip-shopper-in-visetos/MWPGSMT08CO001.html)
- 13–21초 좌상단: Boston 형태, 두 top handle, 양쪽 detachable strap,
  매달린 tag가 보인다. 이는 MCM Ella 제품군의 Boston·top handle·detachable
  strap·hang tag 설명과 일치한다.
  [Ella 공식 제품군](https://us.mcmworldwide.com/en_US/mcm-icons/ella-bags),
  [Ella 공식 PDP](https://us.mcmworldwide.com/en_US/women/bags/top-handle-bags/ella-boston-bag-in-visetos/MWBFAEA03CO001.html)
- 13–21초 우하단: monogram backpack, top carry handle, 앞면 가로 zip
  pocket, logo plaque가 보인다. 현재 catalog의 Aren Nova 후보와 일치하지만,
  영상만으로 ECONYL 소재나 Aren/Stark의 정확한 SKU를 확정하지 않는다.
  [MCM 공식 backpack listing](https://us.mcmworldwide.com/en_US/bags/backpacks)

## 좌표와 checkpoint

좌표는 `video_normalized`이며 `(0,0)`은 영상 좌상단, `(1,1)`은 영상 우하단이다.
각 후보는 시작·중간·끝 checkpoint에서 같은 상품이 polygon 안에 있고 다른 상품이
들어오지 않는지 확인해야 한다.

| AOI ID | 구간 | Polygon points | Checkpoints |
| --- | --- | --- | --- |
| `mcm-lookbook-v2-toni-grid-top-left` | `[5000,12000)` | `[[0.08,0.02],[0.42,0.02],[0.42,0.49],[0.08,0.49]]` | 5000 / 8500 / 11000 |
| `mcm-lookbook-v2-toni-grid-top-right` | `[5000,12000)` | `[[0.58,0.02],[0.92,0.02],[0.92,0.49],[0.58,0.49]]` | 5000 / 8500 / 11000 |
| `mcm-lookbook-v2-toni-grid-bottom-left` | `[5000,12000)` | `[[0.08,0.51],[0.42,0.51],[0.42,0.98],[0.08,0.98]]` | 5000 / 8500 / 11000 |
| `mcm-lookbook-v2-toni-grid-bottom-right` | `[5000,12000)` | `[[0.58,0.51],[0.92,0.51],[0.92,0.98],[0.58,0.98]]` | 5000 / 8500 / 11000 |
| `mcm-lookbook-v2-ella-grid-top-left` | `[13000,21000)` | `[[0.06,0.01],[0.44,0.01],[0.44,0.49],[0.06,0.49]]` | 13000 / 17000 / 20500 |
| `mcm-lookbook-v2-aren-nova-backpack-grid-bottom-right` | `[13000,21000)` | `[[0.60,0.49],[0.90,0.49],[0.90,0.99],[0.60,0.99]]` | 13000 / 17000 / 20500 |

전체 후보의 `product_id`, controlled tags, 부모 관계와 상세 review action은
r3 JSON에 기록되어 있다. 첫 3-B는 `mcm-lookbook-v2-ella-grid-top-left`
하나만 승인해도 수행할 수 있다. Toni top-left를 더 확실한 상품으로 판단하면
그 AOI 하나를 대신 선택해도 된다.

## 의도적으로 매핑하지 않은 구간

- `[0,5000)`: intro/title
- `[12000,13000)`: grid 전환
- `[13000,21000)` 우상단: structured flap bag이나 현재 10개 catalog에서
  정확한 product ID 미확정
- `[13000,21000)` 좌하단: flat monogram zip pouch이나 정확한 product ID 미확정
- `[21000,22000)`: model 장면 전환
- `[22000,28000)`: 모델이 가방을 들고 이동하며 정적 polygon이 옷·손·배경을
  포함할 수 있어 dynamic segmentation 전에는 제외
- `[28000,33500)`: closing transition/card

불확실한 영역을 가장 비슷한 상품으로 바꾸지 않는다. 서로 다른 상품의 AOI가
겹치면 Backend는 `ambiguous_product`로 처리한다.

## Owner 검수 기록

승인된 Toni top-left 항목은 위 partial-approval 표와 r3 JSON의
`owner_signoff`에 기록했다. 나머지 후보를 승인하려면 아래 절차를 별도로
반복해야 한다.

```text
검수자 이름: __________________________________
검수일(YYYY-MM-DD): ___________________________

[ ] Toni grid 4개가 모두 mcm-toni-medium-disco-visetos임을 확인
[ ] Ella 좌상단이 mcm-ella-small-disco-visetos임을 확인
[ ] Backpack 우하단이 mcm-aren-nova-medium-backpack-econyl임을 확인
    (아니면 해당 exposure를 거절하고 Stark인지 기록)
[ ] 각 선택 AOI를 start/mid/end checkpoint에서 확인
[ ] 선택 AOI끼리 서로 다른 상품으로 겹치지 않음을 확인
[ ] demo용 0.04 normalized margin을 수용

결정:  [ ] approve_selected_exposures   [ ] reject_and_request_redraw
3-B에 사용할 최소 AOI ID: ____________________
검수자 서명/확인: ______________________________
```

## Margin 근거

현재 calibration-error aggregate가 없어 production 값은 아직 없다. 후보 polygon은
demo 전용으로 `0.04 normalized`를 사용하며 1280x720에서 가로 `51.2px`, 세로
`28.8px`에 해당한다. 이는 내부 임시 허용 범위 `0.03–0.05`의 중간값이다.
사용자가 이 값을 3-B demo용으로 확인할 수는 있지만 production 승인으로 간주하지
않는다. 실제 배포 전에는 `1.5 × calibration-error P95`로 교체하고 overlap을
다시 계산한다.

## 승인 후 순서

1. owner가 r3 JSON의 `owner_signoff`와 위 worksheet를 채운다.
2. 승인한 exposure만 새 `approved` metadata revision으로 복사한다. 기존 pending
   fixture는 보존한다.
3. `test_v2_aoi.py`와 contract 검증을 실행한다.
4. 승인된 whole-product AOI 하나로 `valid gaze → captured video_time_ms → AOI
   match → product/component/tag aggregate` 3-B를 실행한다.
5. 3-B 통과 전에는 Vision 전체 완료로 표시하지 않는다.
