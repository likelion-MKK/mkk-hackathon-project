# Recommendation Service

## 소유자

박형진(BE)이 소유한다. MVP 연구용 추천은 Eye/AOI를 주점수로 하고, 유효한 Face 반응을 더 낮은 비중의 보조 점수로 반영한다. 신호별 feature·정확한 가중치와 최종 알고리즘은 자체 검증 전까지 확정하지 않는다.

## 입력

- API adapter가 활성 세션에서 만든 privacy-minimized 상품별 관심 feature
- 영상·manifest·모델·taxonomy·신호 정의 version
- 세션 완료 또는 설정된 집계 trigger

개별 `ProductAttentionEvent`, `ExpressionSample`은 API 집계 경계에서만 처리하고
영속화하지 않는다. 활성 세션에서는 유효 Eye/AOI 관심 feature와, 단일 상품에
안전하게 귀속된 유효 Face 반응 feature만 상품별로 집계해 추천 엔진에 전달한다.
Face feature는 Eye/AOI보다 낮은 비중으로만 사용하며, 원본 표정 score·frame·좌표와
개별 event payload는 엔진에 전달하지 않는다.

Face score가 무효·결측이거나 상품 귀속이 불명확하면 그 상품의 Face 항을 제외하고
Eye/AOI만으로 실행한다. 이를 중립·무관심 또는 0점짜리 Face 반응으로 바꾸지 않으며,
Face 실패만으로 충분한 Eye/AOI 추천을 `insufficient_data`로 바꾸지 않는다.

현재 `mock/` 구현은 개발·CI용 결정적 Eye/AOI 흐름만 제공한다. Face 보조 점수를 쓰는
연구용 엔진은 [`ADR-0005`](../../docs/adr/0005-mvp-face-response-recommendation.md)의
feature 정의와 Gate가 구현된 별도 PR에서 연결한다.

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
