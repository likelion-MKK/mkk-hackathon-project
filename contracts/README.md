# Contract v1과 중앙 추천 AI v2

이 디렉터리는 Kiosk, Eye, Face, AOI Mapper, Backend, 추천 엔진과 Manager 화면이 독립적으로 개발될 수 있도록 JSON 경계를 정의합니다. 모든 schema는 JSON Schema Draft 2020-12를 사용합니다. 기존 `/api/v1`과 v1 fixture는 호환·replay 기준으로 보존하고, 신규 중앙 추천 경로는 `schema_version=2.0`의 별도 major contract를 사용합니다.

## 현재 신규 경로: 중앙 추천 AI v2

| Schema | 정상 fixture | 경계 |
| --- | --- | --- |
| `v2/frame-observation-v2.schema.json` | `examples/frame-observation-v2.valid.json` | 같은 frame의 시선·AOI·관찰 가능한 얼굴 동작·저수준 파생 신호 |
| `v2/observation-batch-v2.schema.json` | `examples/observation-batch-v2.valid.json` | Kiosk에서 API로 보내는 최대 256개 observation envelope |
| `v2/product-recommendation-profile-v2.schema.json` | `examples/product-recommendation-profile-v2.valid.json` | 중앙 AI가 선택할 수 있는 정확히 10개 상품과 controlled tag |
| `v2/recommendation-evidence-v2.schema.json` | `examples/recommendation-evidence-v2.valid.json` | 결정적 feature extractor가 만드는 내부 A/B/C model payload |
| `v2/recommendation-decision-v2.schema.json` | `examples/recommendation-decision-v2.valid.json` | 중앙 AI 출력 검증 후 공개하는 Top 1 terminal 결정 |
| `v2/product-detail-v2.schema.json` | `examples/product-detail-v2.valid.json` | reviewed 단일 상품 표시 profile |
| `v2/manager-product-request-v2.schema.json` | `examples/manager-product-request-v2.valid.json` | 명시적인 고객 Top 1 상품 요청 |
| `v2/manager-event-v2.schema.json` | `examples/manager-event-v2.valid.json` | 요청된 Top 1만 전달하는 Manager polling event |

Transport routing은 다음과 같습니다.

- `POST /api/v2/sessions/{session_id}/observations`: `ObservationBatchV2`
- `POST /api/v2/sessions/{session_id}/complete`: 추천 job 생성, HTTP 202의 pending receipt 반환
- `GET /api/v2/sessions/{session_id}/recommendation`: 처리 중이면 HTTP 202 pending receipt, terminal이면 HTTP 200 `RecommendationDecisionV2`
- `DELETE /api/v2/sessions/{session_id}`: 활성 파생 observation·집계·멱등 키 폐기
- `GET /api/v2/products/{product_id}`: nullable source/asset reason을 포함한 reviewed 단일 상품 조회
- `POST /api/v2/sessions/{session_id}/manager-product-requests`: 고객이 명시적으로 선택한 Top 1 요청만 생성
- `GET /api/v2/manager/events`: `customer_product_request` v2 event만 polling

`pending`은 model 결정이 아니므로 `RecommendationDecisionV2.status`에 넣지 않습니다. terminal status는 `completed|insufficient_data|failed`뿐이고, `completed`일 때 제공된 10개 catalog ID 중 정확히 하나만 `selected_product_id`로 반환합니다.

### v2 저수준 신호와 연속성

- 여기서 “로우 데이터”는 원본 frame이 아니라 frame에서 추출한 좌표·quality·관찰 가능한 action score와 저수준 변화량입니다. image/frame bytes, base64/data URI, 얼굴 embedding·landmark와 원본/소스 경로는 금지합니다.
- `session_offset_ms`는 세션의 첫 accepted analysis frame을 `0`으로 한 상대 시간이고 세션 안에서 감소하지 않습니다. `captured_at_mono_ms`는 producer clock의 캡처 시각입니다.
- 이동·지속·복귀 후보와 score 변화는 같은 session, video, `playback_epoch`, taxonomy와 시간순 frame만 이어 계산합니다. session/video/epoch 변경, out-of-order, invalid·missing modality 또는 설정된 gap이면 이전 상태를 reset하며 경계를 넘어 carry하지 않습니다.
- reset 직후 이동·속도·복귀 후보·score 변화/변화율은 `0`이나 `false`로 채우지 않고 `null`과 `no_previous_observation` 또는 `continuity_reset` 같은 reason으로 표현합니다. `continuous_observation_ms=0`은 새 유효 구간의 실제 시작값입니다.
- 얼굴 score 변화 map은 두 frame에 모두 존재하는 taxonomy label의 교집합만 계산합니다. 한쪽에 없는 label을 `0`으로 대체하지 않습니다. `return_candidate`와 `sustained_actions`도 확정 감정·성격·구매 의도가 아니라 세션 내 관찰 신호입니다.
- Evidence summary도 같은 원칙을 유지합니다. 비교 가능한 interval이 없으면 movement·return count 또는 action change aggregate를 `null+reason`으로 두며, numeric `0`과 빈 sustained action 배열은 실제로 측정했으나 변화·후보가 없을 때만 사용합니다.

### v2 결정 grounding과 고객 문구

- Model input A는 summary+evidence windows+timeline, B는 timeline+summary, C는 summary+evidence windows입니다. 세 variant는 같은 feature/catalog/prompt version으로 평가합니다.
- `reason_codes`, `exploration_tendency_code`, controlled catalog tag만 고객 문구 template의 입력으로 사용합니다. model이 만든 `reason.explanation`, `evidence.statement`, `style.summary`는 audit/debug 정보이며 고객에게 그대로 노출하지 않습니다.
- `exploration_tendency_code`는 현재 세션의 상품 탐색 범위를 나타낼 뿐 사용자 유형이나 심리 진단이 아닙니다.
- 각 decision evidence의 `product_id`는 선택 상품과 같아야 합니다. A/C의 typed `evidence_refs`는 같은 Evidence의 `{kind=window, ref_id=window_id}`만, B는 `{kind=frame, ref_id=timeline.frame_id}`만 참조합니다. Window의 `product_id` 또는 frame attention candidate도 선택 상품과 같아야 합니다.
- Decision의 `version.input_variant`는 실제 사용한 Evidence A/B/C variant와 같아야 합니다.
- Schema만으로 보장할 수 없는 `selected_product_id ∈ 제공 catalog`, 10개 `product_id` 유일성, evidence 참조 무결성, session offset 단조성은 consumer와 contract/eval test가 확인합니다.

### v2 상품 source와 보존

- `mcm-us-listing-names-v2-2026-08-16` seed는 공식 all-bags listing에서 확인된 상품명 10개를 사용하지만 추천 tag·요약은 팀 작성 demo 정보입니다. style code와 개별 상품 URL은 확인 전이므로 이름 기반 team ID를 사용합니다.
- 미검증 개별 URL, 승인되지 않은 image/QR asset은 만들지 않고 각각 `null+reason`으로 둡니다. `approved_asset=false`인 record는 고객용 자산 catalog로 승격하지 않습니다.
- ObservationBatch와 RecommendationEvidence는 활성 세션 메모리의 일시 데이터입니다. 추천 terminal/취소/TTL 시 frame-level 좌표·score·변화량·window/timeline·중복 제거 키를 폐기하고 DB·파일·로그·cache·queue·backup에 저장하지 않습니다.
- DB에는 승인된 상품 profile, terminal RecommendationDecision의 최소 audit metadata와 향후 별도 동의·계약이 승인된 conversion outcome만 둡니다. 운영 로그에는 payload 대신 request ID, status, version과 count만 남깁니다.

## Contract v1 호환 경로

## API 계약

- `openapi.yaml`: FastAPI가 구현할 REST API의 OpenAPI 3.1 계약
- `requests/manager-product-request.schema.json`: S04 고객 제품 요청 body 계약
- `events/manager-event.schema.json`: 고객의 S04 제품 요청을 매니저 화면에 전달하는 polling 이벤트 계약
- `events/reaction-batch.schema.json`: Kiosk·AI 영역이 Backend로 전송할 파생 반응 batch 계약
- `vision-stream-v1/`: Kiosk와 Vision Gateway 사이의 token, text control/result, binary frame envelope 계약

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

### MVP C안의 파생 event 처리

- `ReactionBatch`는 전달·검증·집계를 위한 transport이며, 개별 event를 영속 보관하는 event history가 아닙니다.
- Backend는 활성 세션 안에서만 `event_id`, `sequence`, `batch_id`로 중복을 제거하고, catalog 상품별 유효 관심 집계를 만듭니다.
- 추천 완료 시 활성 집계와 중복 제거 키를 폐기합니다. 개별 event payload, 좌표, frame ID, 캡처 시각과 표정 score는 DB·파일·로그·cache·queue·backup에 남기지 않습니다.
- TTL·취소·재시작 경계는 실제 Kiosk client 연결 전 별도 session lifecycle Contract에서 확정합니다.

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

원격 추론이 승인되더라도 이 JSON Contract v1과 일반 REST API의 금지 원칙은 유지합니다. Kiosk와 Vision Gateway 사이의 일시적 binary frame transport는 [`Vision Stream v1`](vision-stream-v1/README.md)에 분리되어 있으며, [`ADR-0001`](../docs/adr/0001-remote-vision-inference.md)이 Accepted되기 전에는 synthetic protocol 검증에만 사용합니다. 실제 image payload fixture는 Git에 저장하지 않습니다.

## JSON Schema 밖의 통합 불변조건

다음 조건은 단일 JSON 문서의 Draft 2020-12 검증만으로 완전히 표현할 수 없으므로 contract test와 소비자 코드가 확인해야 합니다.

- 각 exposure에서 `start_ms < end_ms`
- 하나의 manifest 안에서 `exposure_id`가 중복되지 않음
- manifest와 catalog가 참조하는 `product_id`가 존재하고 일치함
- batch와 내부 event의 `session_id`, `video_id`가 envelope와 일치함
- batch 안의 `event_id`와 세션 sequence가 중복되지 않음
- Top 2의 rank가 각각 `1`, `2`이고 `product_id`가 서로 다름
- Manager product request에는 `request_id`와 `recommendation_id`만 포함하고 상품 목록을 포함하지 않음
- `ConversionOutcome.outcome_id`의 동일 재전송은 같은 문서일 때만 멱등 처리하며, 다른 문서 재사용은 conflict로 거부함
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
