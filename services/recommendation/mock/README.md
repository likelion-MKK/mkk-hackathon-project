# Mock Recommendation Engine

승인된 fixture에 대해 결정적인 Top 2 또는 데이터 부족 상태를 반환해 S04·API·Manager 흐름을 개발한다. 결과에는 mock임을 식별하는 engine/algorithm version을 반드시 포함하며, 실제 추천 성능 평가에 사용하지 않는다.

유효한 in-video `ProductAttentionEvent`의 후보를 세션 `sequence` 오름차순으로 처리하고, 같은 event 안에서는 contract 후보 배열 순서를 유지한다. catalog에 있는 서로 다른 첫 두 상품을 선택하며, 두 개를 만들 수 없으면 `not_enough_valid_attention`을 반환한다.
