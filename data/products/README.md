# 예제 상품 catalog

`catalog.example.json`은 Contract v1과 UI 개발을 위한 가상 fixture입니다. `Example Product` 이름과 `example.invalid` URL은 실제 MCM 상품 정보가 아닙니다.

실제 catalog에는 확인된 상품명, 공식 이미지 URL, 공식 상품 URL과 생성 완료된 QR 자산 경로만 넣어야 합니다. 상품 ID는 lookbook manifest와 추천 결과에서 동일하게 사용합니다.

`mcm-demo-recommendation-profile-v2.json`은 중앙 추천 AI의 계약·A/B/C 평가를 위한 정확히 10개 seed입니다. `mcm-us-pdp-verified-v3-2026-08-18` revision은 사용자 승인 공식 MCM US PDP URL의 slug 상품명과 URL에 포함된 SKU identity를 사용하며, controlled tag와 추천 요약은 팀 작성 정보입니다.

- 공식 PDP 본문 자동 조회가 HTTP 403으로 차단되어 색상·치수·무게·수납·잠금·현재 판매 상태와 소재의 세부 구성은 검증하지 않았습니다.
- 공식 image 사용 승인·license 검토와 QR 생성이 끝나지 않아 `image_asset_path`, `qr_asset_path`는 각각 `null+reason`입니다. 승인되지 않은 URL이나 자산 경로를 추측해 만들지 않습니다.
- `source_status=official_product_page_verified_assets_pending`, `approved_asset=false`인 동안 고객용 자산 catalog로 승격하지 않습니다.
- Backend DB seed, lookbook manifest와 Kiosk UI가 연결될 때는 이 파일의 `catalog_version`과 동일 `product_id`를 사용해야 합니다.

## 검수 완료 v4 상품과 로컬 사진

`mcm-submission-recommendation-profile-v4.json`과 동일 revision의 matching profile은
검수 완료 상품 10개를 사용합니다. Supabase에 등록된 이 revision의 이미지 경로는
`assets/products/<product_id>/<product_id>.jpeg`이며, 사진 원본 자체를 DB에 저장하는
필드는 아닙니다.

로컬 Kiosk의 `apps/kiosk/public/assets/products/`에 해당 사진 10개를 포함합니다.
기존 상품 자산 승인 커밋 `de442f2593223ba31101fbc31d18204e01ff6390`의 원본을
복원했으며, 상품 ID·공식 URL·SHA-256을 대조해 바이트 변경 없이 경로만 맞췄습니다.
`mcm-submission-assets-v4.json`에 출처 커밋과 기존 승인 note·해시를 보존합니다.
원본은 `.jpeg` 파일명에 AVIF로 인코딩되어 있어, 경로 호환성을 유지하면서 실제
브라우저 디코딩도 확인해야 합니다. QR은 v4 catalog의 기존 `null + reason`을 유지합니다.
