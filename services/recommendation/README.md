# Recommendation Service

## 소유자

박형진(BE)이 소유한다. 신호별 feature·가중치와 최종 알고리즘은 논문 조사와 자체 검증 전까지 확정하지 않는다.

## 입력

- API adapter가 활성 세션에서 만든 privacy-minimized 상품별 관심 feature
- 영상·manifest·모델·taxonomy·신호 정의 version
- 세션 완료 또는 설정된 집계 trigger

개별 `ProductAttentionEvent`, `ExpressionSample`은 API 집계 경계에서만 처리하고
추천 엔진에 전달·영속화하지 않는다. MVP에서는 표정 score를 상품 feature나
추천 점수에 사용하지 않는다.

## 출력

- 상품별 파생 feature와 알고리즘 실행 상태
- Top 2와 algorithm version을 가진 `RecommendationResult`

## 금지사항

- 원본 프레임이나 얼굴 식별 정보를 입력으로 요구하지 않는다.
- 결측·무효 신호를 무관심이나 중립 반응으로 간주하지 않는다.
- 연구 전 가중치를 실제 추천 품질이 검증된 값처럼 고정하지 않는다.
- Mock 결과는 환경과 결과 payload에서 명확히 구분한다.

- [`mock/`](mock/README.md): 전체 흐름 개발용 결정적 결과 경계
- [`engine/`](engine/README.md): 검증된 실제 알고리즘을 연결할 인터페이스 경계
