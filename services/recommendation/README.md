# Recommendation Service

박형진(BE)이 소유하는 중앙 추천 경계입니다. 신규 v2 경로는 Eye·Face·AOI producer가 만든 파생 저수준 신호를 세션 메모리에서 결정적으로 정리한 뒤, self-hosted Korean/JSON instruction model이 제공된 10개 catalog ID 중 Top 1을 선택하게 합니다. 특정 model을 심리·감정 분석 모델로 포장하거나 표정·시선을 실제 감정, 성격 또는 구매 의도로 확정하지 않습니다.

## 활성 v2 흐름

1. API는 `ObservationBatchV2`를 받아 같은 `frame_id`의 gaze, attention, expression과 derived signal을 merge합니다.
2. Feature extractor는 version과 결측 reason을 보존해 `RecommendationEvidenceV2`의 summary, evidence window와 선택적 timeline을 만듭니다.
3. Prompt runner는 같은 catalog와 prompt로 A/B/C payload를 평가합니다. A=summary+window+timeline, B=timeline+summary, C=summary+window입니다.
4. Model JSON은 `RecommendationDecisionV2` schema, catalog membership, evidence reference와 privacy gate를 모두 통과해야 공개됩니다. 실패하면 임의 보정하지 않고 `failed` 또는 `insufficient_data`를 반환합니다.
5. Terminal 결과 뒤에는 frame-level observation, timeline, window와 session aggregate를 폐기합니다.

모델 입력에는 정확히 10개 상품의 `product_id`, controlled tag, 팀 작성 추천 summary만 사용합니다. `official_product_url`, image와 QR asset이 미검증이면 `null+reason`을 유지하며 추천 model이 URL이나 상품 정보를 만들게 하지 않습니다.

## 입력·출력 계약

- Transport input: `contracts/v2/observation-batch-v2.schema.json`
- Internal model input: `contracts/v2/recommendation-evidence-v2.schema.json`
- Catalog profile: `contracts/v2/product-recommendation-profile-v2.schema.json`
- Terminal output: `contracts/v2/recommendation-decision-v2.schema.json`

`pending`은 model 결과가 아니라 HTTP 202 receipt입니다. Terminal decision은 `completed|insufficient_data|failed`만 허용하고, completed는 제공 catalog 안의 단일 `selected_product_id`를 가져야 합니다.

고객 화면 문구는 model 자유 문장을 그대로 표시하지 않습니다. allowlisted `reason_codes`, session-only `exploration_tendency_code`와 DB의 controlled tag를 검토된 template에 넣습니다. “@@ 유형”처럼 사람의 심리·성격 유형을 단정하는 표현은 금지합니다.

## v1 호환·replay 경계

현재 `engine/interface.py`, `mock/`과 `engine/research_gaze.py`는 v1 `RecommendationResult` Top 2 개발 fixture/replay를 보존하는 compatibility 구현입니다. `gaze-score-v0` 가중치는 실제 추천 품질이 검증된 운영 정책이 아니며 중앙 AI v2의 fallback 또는 기본 engine이 아닙니다. 상세 한계와 replay gate는 [`engine/README.md`](engine/README.md)에 있습니다.

기존 `ConversionOutcome`은 향후 동의·보존·학습 정책을 별도로 승인할 때 연결할 follow-up v1 compatibility 계약으로만 유지합니다. 초기 v2 추천에서 구매·호감 정보를 수집하거나 model 가중치를 자동 변경하지 않습니다.

## 금지사항

- 원본 frame/image bytes, base64/data URI, 얼굴 embedding·landmark와 원본/소스 경로를 REST, model payload, DB, cache, queue, 로그 또는 APM에 포함하지 않습니다.
- 결측·무효·연속성 reset을 `0`, `false`, 중립 표정이나 무관심으로 대체하지 않습니다.
- Summary의 이동·복귀 후보·action 변화도 계산 가능한 interval이 없으면 `null+reason`이며, 측정된 0과 구분합니다.
- model이 catalog 밖 ID, 심리 진단 또는 근거 없는 상품 정보를 내면 repair해 노출하지 않고 검증 실패로 처리합니다.
- 실제 model 성능·지연·GPU 요구량을 실행 전 문서상 수치만으로 통과 처리하지 않습니다.

- [`mock/`](mock/README.md): v1 UI/API 개발용 결정적 Top 2 fixture
- [`engine/`](engine/README.md): v1 replay baseline과 신규 v2 중앙 AI 경계 설명
- [`experiments/recommendation/`](../../experiments/recommendation/README.md): versioned prompt, model candidate registry와 A/B/C evaluation harness
