# 예제 상품 catalog

`catalog.example.json`은 Contract v1과 UI 개발을 위한 가상 fixture입니다. `Example Product` 이름과 `example.invalid` URL은 실제 MCM 상품 정보가 아닙니다.

실제 catalog에는 확인된 상품명, 공식 이미지 URL, 공식 상품 URL과 생성 완료된 QR 자산 경로만 넣어야 합니다. 상품 ID는 lookbook manifest와 추천 결과에서 동일하게 사용합니다.

`mcm-demo-recommendation-profile-v2.json`은 중앙 추천 AI의 계약·A/B/C 평가를 위한 정확히 10개 seed입니다. `mcm-us-pdp-verified-v3-2026-08-18` revision은 사용자 승인 공식 MCM US PDP URL의 slug 상품명과 URL에 포함된 SKU identity를 사용하며, controlled tag와 추천 요약은 팀 작성 정보입니다.

- 공식 PDP 본문 자동 조회가 HTTP 403으로 차단되어 색상·치수·무게·수납·잠금·현재 판매 상태와 소재의 세부 구성은 검증하지 않았습니다.
- 공식 image 사용 승인·license 검토와 QR 생성이 끝나지 않아 `image_asset_path`, `qr_asset_path`는 각각 `null+reason`입니다. 승인되지 않은 URL이나 자산 경로를 추측해 만들지 않습니다.
- `source_status=official_product_page_verified_assets_pending`, `approved_asset=false`인 동안 고객용 자산 catalog로 승격하지 않습니다.
- Backend DB seed, lookbook manifest와 Kiosk UI가 연결될 때는 이 파일의 `catalog_version`과 동일 `product_id`를 사용해야 합니다.
