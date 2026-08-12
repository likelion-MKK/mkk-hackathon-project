# Contract v1

이 디렉터리는 Kiosk, Eye, Face, AOI Mapper, Backend, 추천 엔진과 Manager 화면이 독립적으로 개발될 수 있도록 JSON 경계를 정의합니다. 모든 schema는 JSON Schema Draft 2020-12를 사용하며 `schema_version`은 `1.0`입니다.

## API 계약

- `openapi.yaml`: FastAPI가 구현할 REST API의 OpenAPI 3.1 계약
- `requests/manager-product-request.schema.json`: S04 고객 제품 요청 body 계약
- `events/manager-event.schema.json`: 고객의 S04 제품 요청을 매니저 화면에 전달하는 polling 이벤트 계약
- `events/reaction-batch.schema.json`: Kiosk·AI 영역이 Backend로 전송할 파생 반응 batch 계약

`GET /api/v1/manager/events?after_sequence={last_sequence}`은 매니저 화면이 1~2초 간격으로 polling하는 이벤트 조회 계약입니다. `event_id`로 중복을 제거하고, 가장 큰 `sequence`를 다음 cursor로 사용합니다.

## Schema와 정상 fixture

| Schema | 정상 fixture | 책임 |
| --- | --- | --- |
| `lookbook-manifest.schema.json` | `examples/lookbook-manifest.valid.json` | 영상 시각별 상품 AOI |
| `product-catalog.schema.json` | `examples/product-catalog.valid.json` | 상품 표시 정보와 QR 자산 참조 |
| `events/gaze-sample.schema.json` | `examples/gaze-sample.valid.json` | viewport 기준 시선과 측정 품질 |
| `events/expression-sample.schema.json` | `examples/expression-sample.valid.json` | 관찰 가능한 표정 점수와 품질 |
| `events/product-attention-event.schema.json` | `examples/product-attention-event.valid.json` | 시선과 AOI의 교차 결과 |
| `events/reaction-batch.schema.json` | `examples/reaction-batch.valid.json` | 파생 반응 event 전송 묶음 |
| `events/recommendation-result.schema.json` | `examples/recommendation-result.valid.json` | 추천 상태와 Top 2 |
| `requests/manager-product-request.schema.json` | `examples/manager-product-request.valid.json` | S04 고객 제품 요청 body |
| `events/manager-event.schema.json` | `examples/manager-event.valid.json` | 고객의 제품 요청 polling 알림 |
| `events/conversion-outcome.schema.json` | `examples/conversion-outcome.valid.json` | 추천 후 착용·구매 기록 |

실행용 데이터 fixture는 다음 두 파일에도 있습니다.

- `data/lookbooks/example/manifest.json`
- `data/products/catalog.example.json`

두 fixture의 상품 ID는 서로 일치하지만 실제 상품이나 영상 정보를 뜻하지 않습니다.

## 공통 규칙

### 식별자와 중복 제거

- 파생 sample/event에는 개인 계정과 무관한 `session_id`를 사용합니다.
- `event_id`는 재전송 중복 제거 키이고 `sequence`는 세션 내 event 순서를 나타냅니다.
- `frame_id`는 동일한 캡처 프레임에서 생성된 Eye·Face 결과를 연결합니다.
- batch envelope는 별도의 `batch_id`와 `batch_sequence`를 가집니다.

### 시간

- `captured_at_mono_ms`와 `video_time_ms`는 추론 완료 시점이 아니라 프레임 캡처 시점을 기준으로 합니다.
- pause, seek, replay 뒤의 같은 영상 시각을 구분하기 위해 `playback_epoch`을 사용합니다.
- manifest 노출 구간은 `start_ms <= video_time_ms < end_ms`인 반개구간입니다.

### 좌표와 무효 신호

- `GazeSample` 좌표는 Kiosk viewport 좌상단 원점의 `0.0~1.0` 정규화 좌표입니다.
- `ProductAttentionEvent` 좌표는 letterbox, crop, resize를 보정한 영상 content 기준 정규화 좌표입니다.
- `valid=false`인 시선은 좌표를 포함할 수 없고 비어 있지 않은 `reason`을 가져야 합니다.
- `ExpressionSample`이 무효이면 `scores`는 빈 object여야 합니다. 결측을 중립 점수로 대체하지 않습니다.
- 영상 밖의 유효한 시선은 `outside_video=true`, 빈 `candidates`, `reason=null`로 표현합니다. 이는 측정 실패와 구분됩니다.
- AOI가 겹치면 `candidates`에 모든 hit와 manifest의 `priority`를 전달합니다. 여기서 최종 상품을 고르지 않습니다.

### 표정 점수

- `scores`는 선택된 Adapter가 공통 taxonomy로 정규화한 관찰값입니다.
- Contract는 특정 감정 label을 미리 확정하지 않습니다. 대응할 수 없는 label은 version이 기록된 taxonomy에서 `unknown`으로 남길 수 있습니다.
- 표정 점수는 감정, 성격 또는 구매 의도의 확정값이 아닙니다.

### 추천 경계

- `RecommendationResult.status=completed`이면 정확히 두 개의 상품을 전달합니다.
- `engine_mode`로 `mock`과 연구 후 구현을 구분합니다.
- Contract v1에는 모델 선택, feature 채택 여부, 신호별 가중치, 내부 추천 점수를 넣지 않습니다.
- `insufficient_data`와 `failed`는 빈 `items`와 명시적인 `reason`을 사용합니다.

### 원본 입력 금지

Schema와 event에는 웹캠 원본 프레임, 이미지 바이트, 얼굴 embedding, blob, base64 payload나 원본 파일 경로를 정의하지 않습니다. Object는 허용된 필드만 받도록 `additionalProperties: false`를 사용합니다. 상품 catalog의 `image_url`은 표시 자산의 외부 참조이며 이미지 payload가 아닙니다.

## JSON Schema 밖의 통합 불변조건

다음 조건은 단일 JSON 문서의 Draft 2020-12 검증만으로 완전히 표현할 수 없으므로 contract test와 소비자 코드가 확인해야 합니다.

- 각 exposure에서 `start_ms < end_ms`
- 하나의 manifest 안에서 `exposure_id`가 중복되지 않음
- manifest와 catalog가 참조하는 `product_id`가 존재하고 일치함
- batch와 내부 event의 `session_id`, `video_id`가 envelope와 일치함
- batch 안의 `event_id`와 세션 sequence가 중복되지 않음
- Top 2의 rank가 각각 `1`, `2`이고 `product_id`가 서로 다름
- Manager product request에는 `request_id`와 `recommendation_id`만 포함하고 상품 목록을 포함하지 않음
- `source_gaze_event_id`가 같은 세션의 실제 GazeSample을 가리킴

## 검증

저장소 루트에서 contract 전용 의존성을 설치하고 validator를 실행합니다.

```powershell
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

validator는 schema 자체, 정상 fixture, 실행용 data fixture와 금지 payload key를 검사해야 합니다. `examples/invalid/`의 파일은 정상 fixture가 아니며, 대응 schema에 의해 거부되는지를 확인할 때만 사용합니다. 현재 의도적인 실패 사유는 `examples/invalid/README.md`에 기록되어 있습니다.

## 호환성

- Contract v1에서는 optional field 추가처럼 기존 소비자가 무시할 수 있는 변경만 허용합니다.
- 필드 삭제, 이름 변경, 의미 변경은 새 major contract에서 진행합니다.
- Schema 변경과 생산자·소비자 구현 변경을 같은 PR에 섞지 않습니다.
- manifest가 바뀌면 `manifest_version`을 올리고 관련 분석 event와 추천 결과에 그 version을 기록합니다.
