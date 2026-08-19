# 의도적으로 유효하지 않은 fixture

이 디렉터리의 JSON은 정상 예제가 아니며 일반 fixture 자동 검증 대상에서 제외합니다. Contract test에서는 각각이 대응 schema 검증에 **실패하는지** 확인하는 용도로만 사용합니다.

## `gaze-sample.invalid.json`

- 대응 schema: `contracts/events/gaze-sample.schema.json`
- 실패 이유: `screen_x_norm` 값이 `1.2`로, viewport 정규화 좌표 범위인 `0.0` 이상 `1.0` 이하를 벗어납니다.
- 이 예제에는 실제 고객 데이터나 원본 프레임이 없습니다.

원본 프레임, 이미지 바이트, blob 또는 base64 payload 필드는 Contract v1에 정의하지 않습니다. 각 object의 `additionalProperties: false` 규칙에 따라 그런 필드도 거부되어야 합니다.

## Contract v2 negative fixture

- `frame-observation-v2.invalid.json`: 결측 gaze 사유가 없고 금지된 `image_base64` 필드를 포함합니다.
- `privacy-raw-frame/frame-observation-v2.invalid.json`: otherwise-valid frame에 `raw_frame`을 추가합니다.
- `privacy-image-bytes/frame-observation-v2.invalid.json`: otherwise-valid frame에 `image_bytes`를 추가합니다.
- `privacy-base64/frame-observation-v2.invalid.json`: otherwise-valid frame에 `image_base64`를 추가합니다.
- `privacy-data-uri/frame-observation-v2.invalid.json`: otherwise-valid frame에 inline `data:image/...` URI를 추가합니다.
- `privacy-face-embedding/frame-observation-v2.invalid.json`: otherwise-valid frame에 `face_embedding`을 추가합니다.
- `privacy-landmarks/frame-observation-v2.invalid.json`: otherwise-valid frame에 `face_landmarks`를 추가합니다.
- `privacy-original-path/frame-observation-v2.invalid.json`: otherwise-valid frame에 `original_path`를 추가합니다.
- `privacy-source-path/observation-batch-v2.invalid.json`: otherwise-valid batch에 `source_path`를 추가합니다.
- `observation-batch-v2.invalid.json`: `observations`가 비어 있습니다.
- `recommendation-evidence-v2.invalid.json`: 결측 Eye 사유가 없고 C안에 필요한 evidence window가 없습니다.
- `product-recommendation-profile-v2.invalid.json`: 10개 미만이며 demo placeholder를 승인 자산으로 표시합니다.
- `recommendation-decision-v2.invalid.json`: 완료 상태인데 선택 상품, 근거와 style이 없고 allowlist 밖 code/variant를 사용합니다.
- `product-detail-v2.invalid.json`: 자산 pending record에 검증되지 않은 개별 상품 URL을 승인 정보처럼 넣습니다.
- `manager-product-request-v2.invalid.json`: allowlist 밖 심리 profile intent를 사용합니다.
- `manager-event-v2.invalid.json`: v2에서 금지한 자동 `recommendation_ready` event를 사용합니다.
- `lookbook-aoi-metadata-v2.invalid.json`: `pending_review` revision에 검수되지 않은 exposure를 넣어 fail-closed 승인 규칙을 위반합니다.
