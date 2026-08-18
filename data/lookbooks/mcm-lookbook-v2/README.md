# 실제 MCM 룩북 v2

`manifest.json`은 재생 identity만 제공하며 상품 exposure를 포함하지 않는다.
`aoi-metadata-v2.json`은 기존 pending fixture로 보존한다. 양유상이 2026-08-18에
Vision 3-B demo용으로 승인한 Toni top-left whole-product AOI 하나는 별도
`aoi-metadata-v2-r3-approved.json` revision에만 들어 있다.

- canonical video ID: `mcm-lookbook-v2`
- byte length: 5,754,164
- duration: 33,500ms
- resolution / FPS: 1280×720 / 24FPS
- SHA-256: `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89`

승인 r3 revision에는 `[5000,12000)`의
`mcm-lookbook-v2-toni-grid-top-left` / `mcm-toni-medium-disco-visetos` /
`whole_product` / `monogram`, `shopper`, `tote`만 들어 있다. 나머지 Toni 후보,
Ella, Aren backpack, component 후보와 미확정 영역은 여전히 pending이다. 기본
Backend는 pending metadata를 사용하며, 3-B test만 approved revision 경로를 명시적으로
주입한다. 승인 전 경로는 `aoi_metadata_unapproved`로 종료하며 임의 product ID를 만들지 않는다.

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
