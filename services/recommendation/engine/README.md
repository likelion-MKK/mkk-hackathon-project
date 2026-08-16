# Recommendation Engine Boundary

신규 운영 방향은 `RecommendationEvidenceV2`와 정확히 10개 `ProductRecommendationProfileV2`를 self-hosted 중앙 판단 model에 전달하고, schema/catalog/evidence 검증을 통과한 단일 `RecommendationDecisionV2`만 공개하는 교체 지점이다. 입력 신호의 quality·결측·continuity reset과 모든 model/prompt/feature/catalog revision을 보존한다.

Model runner는 API Pydantic/store를 import하지 않고 다음 순서를 지킨다.

1. 결정적 extractor가 A/B/C 중 선택된 payload를 만든다.
2. self-hosted model은 제공된 catalog ID 하나만 선택하거나 데이터 부족을 반환한다.
3. JSON Schema, catalog membership, evidence window reference, 금지 표현과 version 일치를 검증한다.
4. 고객 문구는 model 자유 문장이 아니라 allowlisted reason/tendency code와 DB tag template으로 조합한다.

현재 `interface.py`, `features.py`, `research_gaze.py`와 `mock/` 코드는 아래 v1 compatibility/replay 경계다. 중앙 AI v2 interface 구현으로 오해하거나 기본 운영 fallback으로 연결하지 않는다.

v1 엔진은 `apps/api/`의 Pydantic 모델이나 store를 import하지 않는다. API adapter는 공개 event를 활성 세션에서 즉시 집계·폐기한 뒤, sanitized feature와 catalog payload만 전달한다. `RecommendationRun.to_payload()`는 v1 `RecommendationResult` 계약으로 검증한 뒤 replay와 compatibility REST 응답에만 사용한다.

## v1 replay baseline: 시선 점수 1차 버전

`research_gaze.py`의 `ResearchGazeScoreEngine`은 실제 추천 품질을 주장하지 않는 연구·replay 전용 구현이다. 상품별 유효 시선 관찰 시간을 100ms 단위로 묶어 같은 짧은 구간의 높은 capture FPS가 점수를 부풀리지 않게 한다. `revisit_count`는 실제로 다시 본 횟수가 아니라, 같은 상품 hit가 나타난 observation run 사이의 간격으로 만든 **재방문 후보 지표**다. invalid sample·frame drop·다른 상품/AOI 관찰도 새 run처럼 보일 수 있으므로 실제 사용자 재방문으로 해석하지 않는다. 기본 300ms gap은 현재 D3 fake의 250ms capture cadence를 위한 연구 가설이며, 실제 sampling FPS가 D5에서 확정되면 replay 검증과 함께 다시 조정한다. 현재 순위 가중치도 관찰 시간 65%, 시간 가중 시선 신뢰도 25%, observation-run 후보 10%라는 초기 가설이다.

기본 정책의 결과 revision은 `gaze-score-v0-b100-g300-w0p65-c0p25-r0p1`이다. bucket/gap 또는 가중치를 바꾸면 revision도 바뀌므로, replay 결과를 같은 `algorithm_version`으로 비교하지 않는다.

- 원본 frame, 좌표, frame ID, 캡처 시각, 개별 event 또는 표정 score는 엔진 입력에 포함하지 않는다.
- 여러 상품이 동시에 후보인 한 관찰은 관찰 비중과 `confidence_total`을 후보 수만큼 나눠 반영한다. 같은 100ms 안에서 후보가 바뀌어 상품별 최대 비중의 합이 100%를 넘으면 상품별 비율을 다시 줄여 한 구간의 총 시간이 100ms를 넘지 않게 한다. AOI의 최종 우선순위 규칙이 확정되면 이 부분은 별도 버전으로 교체한다.
- 표정 정보는 이번 버전에 사용하지 않는다. EyeTrax 현재 valid sample의 confidence가 모두 `1.0`이면 confidence 25% 항목은 상품 간 순위를 구분하지 않으며, 품질 신호가 검증되기 전까지 초기 연구 가중치로만 본다.
- v1 compatibility API의 기본값은 계속 `MockRecommendationEngine`이다. 연구 엔진은 명시적으로 주입한 테스트·replay 환경에서만 사용하며 결과에 `engine_mode: research_version`와 위 revision을 표시한다. 이는 신규 v2 중앙 추천 정책을 뜻하지 않는다.

## 기본 엔진 전환 전 replay gate

다음 fixture를 통과하기 전에는 이 연구 엔진을 Kiosk 기본값으로 전환하지 않는다.

- 250ms 정상 연속 hit
- 중간 frame 1개 누락 후 동일 상품 hit
- 다른 상품 또는 빈 AOI로 이탈 후 복귀
- invalid sample 후 복귀
- 실제 간격 299ms·300ms·301ms와 bucket 경계가 다른 경우
- `playback_epoch`이 바뀌는 seek/replay
- 서로 다른 confidence가 순위에 미치는 영향
