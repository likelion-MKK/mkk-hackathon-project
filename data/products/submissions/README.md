# 상품 조사 제출 안내

이 폴더는 추천 catalog에 반영하기 전의 **상품 조사 원본**을 모아 두는 곳입니다.
Supabase production DB, migration, API 코드는 이 폴더의 작업 대상이 아닙니다.

상품 하나당 JSON 파일 하나를 만들고, 파일 이름은 기존 canonical `product_id`와
같게 작성합니다.

```text
data/products/submissions/
  mcm-toni-medium-disco-visetos.json
  mcm-diamant-3d-small-calfskin.json
  ...
```

## 작성 원칙

상품 정보는 짧은 추천 문장만 쓰지 말고, 사람이 검수할 수 있도록 `research`에
상세한 사실을 기록합니다. 그중 추천 모델이 실제로 비교할 값은
`recommendation_profile`에 controlled tag와 정규화된 스타일 값으로 다시 적습니다.

- 공식 MCM 상품 페이지와 공식 listing을 우선 출처로 사용합니다.
- 확인한 사실과 조사자의 해석을 구분합니다.
- 소재, 색상, 크기, 무게, 수납, 손잡이·스트랩, 잠금 방식, 시각적 특징,
  사용 상황과 관리 정보를 가능한 한 자세히 채웁니다.
- 공식 수치를 확인하지 못한 항목은 추측하지 말고 `null`과
  `not_verified_reason`으로 남깁니다.
- `recommendation_summary`는 상품의 관찰 가능한 특징만 설명합니다.
  고객의 성격·감정·구매 의도를 추론하지 않습니다.
- 가격, 재고, 판매 상태처럼 변할 수 있는 정보는 출처와 확인 날짜를 함께 남깁니다.
- 이미지 파일, QR 파일, raw image bytes, base64, embedding은 제출 JSON에 넣지 않습니다.
  이미지는 URL과 사용 승인 근거만 적습니다.

`product_id`는 현재 10개 canonical ID 중 하나를 그대로 사용합니다. 새로운 ID를
임의로 만들거나 기존 상품을 삭제·교체하지 않습니다.

## 파일 구조

`template.json`을 복사해 상품 파일을 만들고 다음을 작성합니다.

- `research`: 상세 상품 조사와 확인되지 않은 항목의 사유
- `recommendation_profile`: DB와 추천 AI에 반영할 controlled profile
- `sources`: 어떤 출처가 어떤 사실을 뒷받침하는지
- `asset_review`: 이미지 사용 승인과 자산 상태
- `review`: 조사자, 확인일, 검수 상태

상세 메모나 페이지별 비교 자료가 필요하면 같은 PR에
`data/products/research/<product_id>.md`를 추가할 수 있습니다. JSON에는
그 문서의 원문을 복사하지 말고 핵심 사실과 출처만 정리합니다.

## 검증

아직 상품 파일을 만들지 않은 템플릿 PR에서는 다음을 실행합니다.

```powershell
python scripts/validate_product_submissions.py --allow-empty
```

10개 상품 파일을 모두 채운 데이터 PR에서는 `--allow-empty` 없이 실행합니다.

```powershell
python scripts/validate_product_submissions.py
```

검증기는 canonical catalog와 비교해 상품 수가 정확히 10개인지, ID가 유효한지,
controlled tag·style 값·공식 출처·검수 metadata가 채워졌는지 확인합니다.

## PR 범위

상품 조사자는 다음 경로만 수정합니다.

```text
data/products/submissions/
data/products/research/
```

다음 파일은 DB/API 담당자가 직렬로 관리합니다.

```text
apps/api/app/v2_postgres.py
apps/api/app/v2_store.py
apps/api/migrations/
contracts/
```

PR이 merge된 뒤 DB 담당자가 조사 JSON을 canonical catalog의 새 revision으로
통합하고, seed/import 검증을 통과한 후 Supabase staging과 production에 순서대로
반영합니다.
