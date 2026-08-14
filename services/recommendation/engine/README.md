# Recommendation Engine Boundary

privacy-minimized 상품 feature와 version 정보를 받아 `RecommendationResult` payload로 변환 가능한 실행 결과를 반환하는 교체 지점이다. 실제 엔진은 입력 신호의 `valid`·quality·결측 의미를 보존하고 재현 가능한 algorithm version을 출력해야 한다.
향후 MVP 연구용 Face 보조 엔진은 Eye/AOI 주 feature와 상품 귀속이 확인된 Face 반응 보조 feature를 함께 사용한다. Face 가중치는 Eye/AOI보다 낮아야 하며, 정확한 값·집계식·coverage Gate는 검증된 `algorithm_version`으로 고정한다.

Face 반응은 실제 감정이나 구매 의도가 아니라 관찰 가능한 얼굴 동작에서 파생한 보조 feature다. 무효·결측·다중 얼굴·상품 귀속 불명확 Face 신호는 점수화하지 않고 Eye/AOI-only 경로를 유지한다. 현재 Mock과 `ResearchGazeScoreEngine`은 개발·CI·replay용 Eye/AOI-only 경로이며, Face feature는 별도 research-engine PR에서 연결한다.

엔진은 `apps/api/`의 Pydantic 모델이나 store를 import하지 않는다. API adapter는 공개 event를 활성 세션에서 즉시 집계·폐기한 뒤, sanitized feature와 catalog payload만 전달한다. 엔진의 `RecommendationRun.to_payload()`는 `RecommendationResult` 계약으로 검증한 뒤 REST 응답에 사용한다.

## 시선 점수 1차 버전

`research_gaze.py`의 `ResearchGazeScoreEngine`은 실제 추천 품질을 주장하지 않는 연구·replay 전용 구현이다. 상품별 유효 시선 관찰 시간을 100ms 단위로 묶어 같은 짧은 구간의 높은 capture FPS가 점수를 부풀리지 않게 한다. `revisit_count`는 실제로 다시 본 횟수가 아니라, 같은 상품 hit가 나타난 observation run 사이의 간격으로 만든 **재방문 후보 지표**다. invalid sample·frame drop·다른 상품/AOI 관찰도 새 run처럼 보일 수 있으므로 실제 사용자 재방문으로 해석하지 않는다. 기본 300ms gap은 현재 D3 fake의 250ms capture cadence를 위한 연구 가설이며, 실제 sampling FPS가 D5에서 확정되면 replay 검증과 함께 다시 조정한다. 현재 순위 가중치도 관찰 시간 65%, 시간 가중 시선 신뢰도 25%, observation-run 후보 10%라는 초기 가설이다.

기본 정책의 결과 revision은 `gaze-score-v0-b100-g300-w0p65-c0p25-r0p1`이다. bucket/gap 또는 가중치를 바꾸면 revision도 바뀌므로, replay 결과를 같은 `algorithm_version`으로 비교하지 않는다.

- 원본 frame, 좌표, frame ID, 캡처 시각, 개별 event 또는 표정 score는 엔진 입력에 포함하지 않는다.
- 여러 상품이 동시에 후보인 한 관찰은 관찰 비중과 `confidence_total`을 후보 수만큼 나눠 반영한다. 같은 100ms 안에서 후보가 바뀌어 상품별 최대 비중의 합이 100%를 넘으면 상품별 비율을 다시 줄여 한 구간의 총 시간이 100ms를 넘지 않게 한다. AOI의 최종 우선순위 규칙이 확정되면 이 부분은 별도 버전으로 교체한다.
- 현재 `gaze-score-v0` 버전에서는 표정 정보를 사용하지 않는다. EyeTrax 현재 valid sample의 confidence가 모두 `1.0`이면 confidence 25% 항목은 상품 간 순위를 구분하지 않으며, 품질 신호가 검증되기 전까지 초기 연구 가중치로만 본다. Face 보조 점수는 ADR-0005의 Gate가 구현된 별도 research-engine 버전에서만 사용한다.
- API의 기본값은 계속 `MockRecommendationEngine`이다. 연구 엔진은 명시적으로 주입한 테스트·replay 환경에서만 사용하며 결과에 `engine_mode: research_version`와 위 revision을 표시한다.

## 기본 엔진 전환 전 replay gate

다음 fixture를 통과하기 전에는 이 연구 엔진을 Kiosk 기본값으로 전환하지 않는다.

- 250ms 정상 연속 hit
- 중간 frame 1개 누락 후 동일 상품 hit
- 다른 상품 또는 빈 AOI로 이탈 후 복귀
- invalid sample 후 복귀
- 실제 간격 299ms·300ms·301ms와 bucket 경계가 다른 경우
- `playback_epoch`이 바뀌는 seek/replay
- 서로 다른 confidence가 순위에 미치는 영향
