# Recommendation Engine Boundary

privacy-minimized 상품 feature와 version 정보를 받아 `RecommendationResult` payload로 변환 가능한 실행 결과를 반환하는 교체 지점이다. feature 정의·가중치·평가 자료가 승인되기 전에는 실제 점수 알고리즘을 두지 않는다. 실제 엔진은 입력 신호의 `valid`·quality·결측 의미를 보존하고 재현 가능한 algorithm version을 출력해야 한다.

엔진은 `apps/api/`의 Pydantic 모델이나 store를 import하지 않는다. API adapter는 공개 event를 활성 세션에서 즉시 집계·폐기한 뒤, sanitized feature와 catalog payload만 전달한다. 엔진의 `RecommendationRun.to_payload()`는 `RecommendationResult` 계약으로 검증한 뒤 REST 응답에 사용한다.
