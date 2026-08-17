# 실제 MCM 룩북 v2

`manifest.json`은 재생 identity만 제공하며 상품 exposure를 포함하지 않는다.
`aoi-metadata-v2.json`에는 실제 MP4를 검사한 fingerprint만 고정했고, 상품·부위
매핑은 아직 `pending_review` 상태다.

- canonical video ID: `mcm-lookbook-v2`
- byte length: 5,754,164
- duration: 33,500ms
- resolution / FPS: 1280×720 / 24FPS
- SHA-256: `dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89`

5번 데이터 작업에서 양유상·박형진·조윤혜 검수를 마친 뒤에만 AOI를 추가하고
`approval_status=approved`와 새 metadata revision으로 올린다. 승인 전 Backend는
`aoi_metadata_unapproved`로 종료하며 임의 product ID를 만들지 않는다.

이 pending 경계까지가 Vision 3-A다. 승인 revision을 만든 뒤 실제 valid gaze가
전체·세부 AOI의 정확한 product/component/tag aggregate로 이어지는 3-B를 다시 통과해야
Vision 전체 완료로 표시한다. 같은 상품의 겹친 AOI는 모두 보존하고, 서로 다른 상품이
겹치는 frame은 ambiguous로 어느 상품에도 귀속하지 않는다.
