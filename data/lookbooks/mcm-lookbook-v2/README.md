# 실제 MCM 룩북 v2

`manifest.json`은 실제 33.5초 영상에서 동료가 작성한 86개 시간·polygon exposure를
`video_normalized` 좌표로 보존한다. `source-aoi-metadata-v1.json`은 exposure prefix를
10개 source 가방의 색상·형태·종류·패턴·액세서리에 연결한다. 둘 모두 source 장면
근거이며 catalog 상품 ID를 확정하지 않는다. Backend가 이 근거를 다시 판정하고 검수된
10개 catalog와 비교하며 Kiosk candidate는 권위 근거로 사용하지 않는다.

- canonical video ID: `mcm-lookbook-v2`
- byte length: 5,754,164
- duration: 33,500ms
- resolution / FPS: 1280×720 / 24FPS
- SHA-256: `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89`

노출 구간은 `[5000,29400)`뿐이다. `[0,5000)`과 `[29400,33500)`은 의도적으로
AOI가 없으며 정상 미매칭으로 처리한다. polygon 밖과 영상 content rect 밖 좌표도
미매칭이고 nearest-product 또는 중립 좌표 fallback을 만들지 않는다.

PR #51의 동영상은 canonical 파일과 exact byte identity는 다르지만 804 frame,
33.5초, 1280×720, 24FPS timeline과 표본 frame의 시각 내용이 일치하는 재인코딩본으로
확인했다. polygon·source feature 값은 수정하지 않고 가져왔다. 다만 PR의 승인자 값은
실제 owner provenance가 아닌 placeholder이므로 source metadata는 `pending_review`다.
운영 Backend는 승인 전 유효 영상 observation을 `aoi_metadata_unapproved`로 종료한다.

기존 승인 r3 revision에는 `[5000,12000)`의
`mcm-lookbook-v2-toni-grid-top-left` / `mcm-toni-medium-disco-visetos` /
`whole_product` / `monogram`, `shopper`, `tote`만 들어 있다. 나머지 Toni 후보,
Ella, Aren backpack, component 후보와 미확정 영역은 여전히 pending이다. 기본
Backend는 pending metadata를 사용하며, 3-B test만 approved revision 경로를 명시적으로
주입한다. source-AOI 추천 경로도 test-only 승인 fixture로만 검증한다.

R4는 실제 원본·Kiosk 사본을 다시 대조해 만든
[`aoi-proposal-2026-08-18-r4.json`](./aoi-proposal-2026-08-18-r4.json),
[`AOI_REVIEW_R4.md`](./AOI_REVIEW_R4.md)와 schema-valid
[`aoi-metadata-v2-r4-pending.json`](./aoi-metadata-v2-r4-pending.json)으로 남긴다.
R4 pending metadata는 owner sign-off 전이므로 exposures가 0개이고, 새 approved revision은 없다.
R3의 Toni top-left sign-off는 Vision 3-B demo 범위만 승인한 것이어서 R4 또는 production
approval로 승격하지 않는다. demo-static-assumptions 파일은 R4의 source나 production metadata가 아니다.

이 pending 경계까지가 Vision 3-A다. 승인 revision을 만든 뒤 실제 valid gaze가
전체·세부 AOI의 정확한 product/component/tag aggregate로 이어지는 3-B를 다시 통과해야
Vision 전체 완료로 표시한다. 같은 상품의 겹친 AOI는 모두 보존하고, 서로 다른 상품이
겹치는 frame은 ambiguous로 어느 상품에도 귀속하지 않는다.
