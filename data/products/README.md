# 예제 상품 catalog

`catalog.example.json`은 Contract v1과 UI 개발을 위한 가상 fixture입니다. `Example Product` 이름과 `example.invalid` URL은 실제 MCM 상품 정보가 아닙니다.

`mcm-demo-recommendation-profile-v2.json`은 중앙 추천 AI와 Backend DB seed가 공유하는 정확히 10개의 검수된 MCM 상품 catalog입니다. `catalog_version=mcm-us-pdp-verified-v3-2026-08-18`이며 모든 항목은 `source_status=team_approved_catalog_record`, `approved_asset=true`입니다. controlled tag와 추천 요약은 해커톤 평가용 팀 작성 정보입니다.

`mcm-recommendation-catalog-assets-v2.json`은 같은 catalog version의 이미지·QR metadata를 상품별 1개씩, 총 20개 보관합니다.

- 이미지 논리 경로는 `assets/products/<product_id>.jpeg`, Kiosk 정적 경로는 `media/products/<product_id>.jpeg`입니다.
- QR 논리 경로는 `assets/qr/<product_id>/official-product.png`, Kiosk 정적 경로는 `media/qr/<product_id>/official-product.png`입니다. 각 QR은 해당 상품의 검수된 `official_product_url`을 직접 인코딩합니다.
- 각 asset kind의 `product_id` 집합은 canonical catalog 10개와 정확히 일치해야 합니다.
- DB에는 `asset_kind`, `relative_path`, 공식 PDP URL, SHA-256과 승인 메모만 저장하며 image/QR bytes는 저장하지 않습니다.
- 실제 파일은 `apps/kiosk/public/media/products/`와 `apps/kiosk/public/media/qr/`에 두고 `python scripts/verify_product_assets.py`로 경로, 정확한 파일 집합과 SHA-256을 검증합니다.

Backend DB seed, 중앙 추천 후보와 Kiosk UI는 이 catalog version과 동일한 product ID를 사용해야 합니다.
