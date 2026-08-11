# Recommendation Engine Boundary

파생 이벤트와 version 정보를 받아 `RecommendationResult`를 반환하는 교체 지점이다. feature 정의·가중치·평가 자료가 승인되기 전에는 구현을 두지 않는다. 실제 엔진은 입력 신호의 `valid`·quality·결측을 보존하고 재현 가능한 algorithm version을 출력해야 한다.
