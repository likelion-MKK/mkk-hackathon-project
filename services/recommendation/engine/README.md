# Recommendation Engine Boundary

privacy-minimized 상품 feature와 version 정보를 받아 `RecommendationResult` payload로 변환 가능한 실행 결과를 반환하는 교체 지점이다. 실제 엔진은 입력 신호의 `valid`·quality·결측 의미를 보존하고 재현 가능한 algorithm version을 출력해야 한다.

엔진은 `apps/api/`의 Pydantic 모델이나 store를 import하지 않는다. API adapter는 공개 event를 활성 세션에서 즉시 집계·폐기한 뒤, sanitized feature와 catalog payload만 전달한다. 엔진의 `RecommendationRun.to_payload()`는 `RecommendationResult` 계약으로 검증한 뒤 REST 응답에 사용한다.

## 시선 점수 1차 버전

`research_gaze.py`의 `ResearchGazeScoreEngine`은 실제 추천 품질을 주장하지 않는 연구·replay 전용 구현이다. 상품별 유효 시선 관찰 시간을 100ms 단위로 묶어 같은 짧은 구간의 높은 capture FPS가 점수를 부풀리지 않게 한다. 그 뒤 관찰 시간 65%, 시간 가중 시선 신뢰도 25%, 다시 본 횟수 10%를 사용해 순위를 정한다.

- 원본 frame, 좌표, frame ID, 캡처 시각, 개별 event 또는 표정 score는 엔진 입력에 포함하지 않는다.
- 여러 상품이 동시에 후보인 한 관찰은 관찰 비중과 `confidence_total`을 후보 수만큼 나눠 반영한다. 같은 100ms 안에서 후보가 바뀌어 상품별 최대 비중의 합이 100%를 넘으면 상품별 비율을 다시 줄여 한 구간의 총 시간이 100ms를 넘지 않게 한다. AOI의 최종 우선순위 규칙이 확정되면 이 부분은 별도 버전으로 교체한다.
- 표정 정보는 이번 버전에 사용하지 않는다.
- API의 기본값은 계속 `MockRecommendationEngine`이다. 연구 엔진은 명시적으로 주입한 테스트·replay 환경에서만 사용하며 결과에 `engine_mode: research_version`, `algorithm_version: gaze-score-v0`를 표시한다.
