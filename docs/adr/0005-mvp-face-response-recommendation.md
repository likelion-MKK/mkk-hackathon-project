# ADR-0005 MVP Face 보조 추천 점수

- 상태: Proposed
- 작성일: 2026-08-15
- 결정 소유자: 박형진(Recommendation·API)
- 공동 리뷰: 정은미(Face), 양유상(Eye·AOI), 조윤혜(Kiosk)
- 관련 결정: `D1-09 MVP 파생 반응 보관 C안`, `ExpressionSample v1`, `ProductAttentionEvent v1`
- 선행 조건: 선택 Face Adapter와 taxonomy의 승인, 상품 귀속·품질 Gate의 통과

## 1. 문제

MVP 추천은 고객의 Eye/AOI 관심을 주된 근거로 사용한다. Face 신호도 고객의 반응을
보완하는 낮은 비중의 근거로 반영해야 하지만, 원본 `ExpressionSample.scores`는 한
프레임의 관찰값일 뿐 특정 상품의 실제 감정·성격·구매 의도를 뜻하지 않는다. 또한
no-face, 여러 얼굴, 품질 저하와 모델 장애를 중립 또는 무관심으로 바꾸면 안 된다.

따라서 추천 엔진에는 원본 표정 score가 아닌, 상품 귀속·유효성·표본 수를 확인한
privacy-minimized Face 반응 feature만 전달해야 한다.

## 2. 제안 결정

### 추천 입력과 비중

상품별 추천 입력은 다음 두 종류다.

| 입력 | 역할 | 추천 점수에서의 원칙 |
| --- | --- | --- |
| Eye/AOI 관심 feature | 주 feature | 상품별 유효 응시·AOI 근거로 순위의 중심을 결정한다. |
| Face 반응 feature | 보조 feature | 유효하고 한 상품에 귀속된 관찰 가능한 얼굴 동작의 시간 집계다. Eye/AOI보다 낮은 비중으로만 순위를 보정한다. |

Face 가중치는 Eye/AOI 가중치보다 항상 작아야 한다. 정확한 값, 점수 변환식과
최소 valid coverage는 결과 평가 전에는 고정하지 않고 `algorithm_version`과 함께
기록한다. Face 반응만으로 상품을 추천하거나, Eye/AOI의 충분한 근거를 뒤집을 수
없게 상한을 둔다.

### Face 반응의 입력 Gate

Face 반응 집계에는 다음을 모두 만족하는 `ExpressionSample`만 사용한다.

1. `valid=true`, `face_detected=true`, `face_count=1`이고 `scores`가 비어 있지 않다.
2. 선택 Adapter의 `model_revision`, `taxonomy_version`과 score 범위가 허용 목록과 일치한다.
3. 승인된 quality·confidence Gate와 최소 표본 수를 만족한다.
4. 같은 세션·`video_id`·`playback_epoch` 안에서 Eye/AOI event와 시간적으로 대응하고, 해당 시점의 후보가 정확히 한 `product_id`다.

후보 상품이 둘 이상이거나 Eye/AOI가 무효이면 Face 반응을 어느 상품에도 배분하지
않는다. raw face score, frame, landmark, embedding, capture time 또는 개별 event
payload는 추천 엔진·DB·로그·queue·cache에 보관하지 않는다.

### Feature 의미

선택 Adapter는 원본 모델 label을 versioned canonical taxonomy의 관찰 가능한 얼굴
동작으로 정규화한다. 예를 들어 MediaPipe Face Landmarker를 선택하면 left/right를
보존한 blendshape 계수를 입력으로 사용하고, `_neutral`은 감정 label이나 점수로
승격하지 않는다.

추천용 `face_response_score`는 세션 baseline 대비 변화, 선택 신호 그룹, 시간창
집계와 coverage를 사용한 파생값이다. 이 값은 실제 감정·성격·구매 의도를 확정하지
않으며, 어떤 동작 label을 쓰고 어떻게 하나의 점수로 만드는지는 fixture와 결과
평가를 통과한 research-engine PR에서 `algorithm_version`으로 고정한다.

### 결측과 fallback

- no-face, multi-face, low-quality, timeout, malformed output, model unavailable과
  상품 귀속 불명확은 Face 항을 비활성화한다.
- 해당 상황을 0점, neutral, 무관심 또는 이전 frame 값으로 보간하지 않는다.
- Eye/AOI가 충분하면 Face 항 없이 Eye/AOI-only로 추천을 계속한다. Face 실패만으로
  `RecommendationResult.status=insufficient_data`를 만들지 않는다.
- Eye/AOI도 부족하면 기존 `insufficient_data` 의미를 유지한다.

## 3. Contract·보관 영향

Contract v1의 `ExpressionSample`, `ProductAttentionEvent`, `ReactionBatch`와
`RecommendationResult`는 변경하지 않는다. Face 반응 feature는 API adapter가 활성
세션 메모리에서 만들고, 추천 완료·취소·TTL 만료·오류 시 즉시 폐기한다.

개별 반응 이력이나 raw face score를 학습·분석 목적으로 장기 보관하려면 별도 동의
version, 보유 기간, 삭제·접근 통제와 Contract·migration 승인을 추가로 받아야 한다.

## 4. 구현 순서

1. 선택 Face Adapter가 taxonomy·valid/invalid·quality metadata를 Contract v1에 맞게 출력한다.
2. API adapter가 유효 Eye/AOI와 Face sample을 제품 하나에만 귀속하는 session-local aggregate를 구현한다.
3. research engine이 versioned `face_response_score`와 Eye/AOI 주점수를 결합하고, Face 비중 상한을 적용한다.
4. Mock은 결정적 Eye/AOI-only 개발·CI 경계로 유지하고, research engine과 혼동하지 않는다.
5. 실제 Kiosk·목표 Vision 서버에서 품질, coverage, 지연, Face-off Eye-only fallback과 privacy 비저장을 검증한다.

## 5. 승인 Gate

- [ ] 선택 taxonomy와 각 source label의 의미·version이 승인됐다.
- [ ] 단일 상품 귀속 규칙과 시간창이 fixture로 검증됐다.
- [ ] baseline, feature 그룹, 최소 valid coverage와 Face 가중치 상한이 `algorithm_version`에 고정됐다.
- [ ] Face를 넣은 결과가 Eye/AOI-only 기준보다 유용한지 비식별 평가 자료로 확인됐다.
- [ ] no-face·multi-face·low-quality·timeout·model unavailable에서 Eye-only 추천이 유지된다.
- [ ] 원본 frame·landmark·embedding·raw score가 DB·로그·cache·queue·artifact에 남지 않는다.
- [ ] 실제 Kiosk·목표 Vision 서버에서 capture-to-result, 지속 FPS와 장시간 안정성을 확인했다.

## 6. 미확정 항목

- 정확한 Face/Eye 가중치와 순위 보정 상한
- Face 반응에 쓸 canonical signal 그룹과 baseline 공식
- Eye/AOI와 Face의 시간창, 최소 표본 수와 quality·confidence threshold
- 결과 평가 기준과 허용 가능한 Face-off fallback 비율
