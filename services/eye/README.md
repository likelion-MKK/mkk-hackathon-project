# Eye Service

## 소유자와 범위

양유상(PL·AI)이 소유한다. 웹캠 프레임에서 viewport 기준 point-of-gaze와 품질을 만들고, 캡처 시점 layout·영상 시각·AOI를 결합해 상품 hit 후보를 만드는 단계까지만 책임진다.

## 입력

- Vision Gateway가 decode한 수명 제한 서버 메모리 frame 참조와 Kiosk 캡처 시점 `FrameContext`
- 화면·영상 layout과 version이 고정된 `LookbookManifest`
- 선택된 adapter 종류와 calibration 설정

## 출력

- viewport 정규화 좌표와 품질을 가진 `GazeSample`
- 영상 좌표 변환·time-aware AOI 판정 뒤의 `ProductAttentionEvent`
- 공개 이벤트에는 Contract 필드인 `producer_id`, 고정 `model_revision`, calibration·manifest version
- `AdapterMetadata.adapter_id`는 선택한 로컬 Adapter 구현을 식별하며 이벤트 payload에는 넣지 않는다.

## 금지사항

- 머문 시간·이탈 후 복귀·이동 feature 또는 최종 추천을 독자적으로 계산하지 않는다.
  이 값은 동일 `frame_id`로 Eye·Face·AOI를 결합하는 v2 feature 단계가 계산한다.
- 무효 시선을 `(0, 0)`으로 만들거나 영상 밖 시선을 임의의 상품에 연결하지 않는다.
- 추론 완료 시점의 영상 시각을 사용하지 않는다.
- 모델 코드·weight·대형 생성물을 이 scaffold에 넣지 않는다.
- 원본 frame을 Adapter 출력·예외·로그·파일·DB·cache에 포함하지 않는다.

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.

## Python Adapter

- 공통 타입과 `EyeAdapter` Protocol: `src/mcm_eye/contracts.py`
- 결정적 개발 Adapter: `src/mcm_eye/adapters/fake.py`
- 해커톤 MVP Adapter: `src/mcm_eye/adapters/eyetrax.py`
- 단위·Contract 호환 테스트: `tests/`

EyeTrax 선택에 따라 Eye 서비스만 Python `3.12.10`, EyeTrax `0.4.0`, MediaPipe `1.0.0`,
NumPy `1.26.4`, OpenCV `4.11.0.86`으로 고정한다. 다른 Python 서비스의 runtime은 바꾸지
않는다. 선택 근거와 제한은 [`ADR-0004`](../../docs/adr/0004-eyetrax-mvp-selection.md)에
기록한다.

`FakeEyeAdapter.calibrate()`는 lifecycle과 `calibration_id` 전달을 검증하는 개발용
placeholder다. 브라우저 기본은 `adaptive-dense5-v2`: 25점 가변 수집과 독립 8점 확인,
부족한 부분만 최대 4점 보완한다. 각 점에서 유효 샘플 15개 및 500ms 표본 폭을 확보하면
이동한다. 사용자 승인에 따라 현재 브라우저 v2는 `webcam-relaxed-v1` 기준을 적용한다.
전체 유효 비율 85%, 대각선 오차 p50 15%·p95 30%가 성공 조건이며, 개별 점은
유효 비율 70%, 오차 p50 25%·p95 40%와 최소 15개 수집 표본을 요구한다.
가변 검증 중 15개 표본 시점의 feature 유효 비율이 85% 미만이면 같은 점에서 한 번만 30개까지
추가 수집한다. 기존 무효 표본과 점당 3.5초·전체 120초 제한을 유지하며 실패는 검출 부족과
위치 오차로 구분한다. 수집 부족을 추가 학습으로 보완하지 않는다.
오류에 따른 보완 뒤에는 새로운 8점으로 최종 검증한다. 자세 확인·수집 중단·frame ID와
표적 표시 시각·세션 종료 처리는 [로컬 보정 v2](../../docs/eye-calibration-local-v2.md)를 따른다.
16점 실험 모드와 고정 시간 비교 모드를 제공하며 실제 카메라 시간·정확도는 미검증이다.
이 수치는 로컬 체험의 허용 오차이며 실제 정확도 향상이나 AOI 성능 검증을 뜻하지 않는다.

시작 전에는 얼굴 중앙·상대 크기·양쪽 눈·각도를 확인한다. 준비 상태가 1초 연속 유지되고
유효 표본 15개를 확보하면 학습으로 넘어간다. 최대 30초 동안 준비하지 못하면
`face_position_not_ready`로 종료한다. 준비 표본은 학습에서 폐기하며 기하값은 worker 밖으로
내보내지 않는다. 얼굴 크기와 각도는 휴리스틱이며 정확도 개선률은 실제 카메라 비교가 필요하다.

기존 standalone `calibrate()`는 25+8점 고정 수집(64초 계획), 최대 1회 시도를 유지한다.
기존 최소 10표본 조건과 복구된 90%/10%/25% Gate를 통과해야 하며 실패를 성공으로
바꾸지 않는다. 새로운 브라우저 보정은 `calibrate_synchronized()` 경로다.
보정 요청 전 추론은 lifecycle 오류다. 브라우저 v2는 학습이 완료된 모델의 품질 검사 실패를
`valid=false`로 보존하면서 `inference_ready=true`인 경우 추론을 계속한다. 해당 좌표는
`confidence=0.35`, revision `+low-confidence`로 표시한다. 학습 전 실패·취소·화면 크기 변경은
좌표를 생성하지 않는다. 기본 adaptive profile은 품질 실패 후 추가 위치 보완을 반복하지 않는다.

품질 검증을 통과한 모델의 유효 좌표는 `confidence=1.0`, 품질 미달인 브라우저 모델의
유효 좌표는 `confidence=0.35`를 사용한다. 이 값들은 실측 정확도가 아닌 정책 가중치다.
`no_face`, `blink`, 비유효한 예측과
viewport 밖 예측은 좌표 없이 `valid=false`로 유지한다.

Dense5 학습과 8점 정확도 Gate에는 원시 좌표만 사용한다. 실제 얼굴 A/B에서 안정화 경로가
오차 p95를 늘렸고, 기존 jitter 비교는 서로 다른 frame pair를 사용해 철회했으므로 기본
모드는 `raw`다. 수정된 동일-pair jitter 지표는 실제 카메라 재실행 전까지 미검증이다.

```text
원시 좌표 -> GazeSample
```

`kalman_ema`는 후속 3점 tune 비교 전까지 명시적으로 선택하는 실험 옵션이며 다음 순서로
처리한다.

```text
원시 좌표 → 급속 이동 2프레임 확인 → EyeTrax Kalman + EMA 0.25 → GazeSample
```

대각선 `35%` 이상이면서 `3.0 diagonal/s` 이상인 이동은 `120ms` 안의 다음 유효 frame이
후보점 대각선 `12%` 안에 있어야 확정한다. 대기 frame은 `rapid_shift_pending`, 역순 frame은
`out_of_order`로 반환한다. invalid 공백 `500ms` 초과, 재보정, session·video·playback epoch
변경과 dispose 때 filter를 초기화한다. 화면 밖 filter 결과는 clamp하지 않는다.

v2 브라우저 보정은 아래 revision에 `+calibration-v2`를 추가한다.
기본 원시 mode revision은 `<source>+raw-v1`, 실험 안정화 mode는
`<source>+gaze-filter-v1`이다. 같은 capture context라도 mode별 event ID가 다르다. 이
revision의 EMA alpha는 `0.25`로 고정하며 CLI와 Adapter config는 다른 값을 거부한다.

`FakeEyeAdapter.infer()`는 입력 `FrameContext`의 `sequence`, `frame_id`, 캡처 시각을 항상
보존한다. 순서 역전 테스트는 `FakeGazeDelivery`가 인접한 두 샘플의 전달 순서만 바꾸며,
샘플 내부 필드는 수정하지 않는다.

```powershell
uv sync --locked
uv run pytest
uv run python scripts/prepare_eyetrax_model.py
uv run python scripts/smoke_eyetrax.py
uv run python scripts/live_eyetrax_demo.py --camera 0 --smoothing raw
```

안정화 실험은 다음처럼 명시적으로 실행한다.

```powershell
uv run python scripts/live_eyetrax_demo.py --camera 0 --smoothing kalman_ema --ema-alpha 0.25
```

모델 준비 스크립트는 `.cache/face_landmarker.task`를 내려받은 뒤 고정 SHA256을 검증한다.
runtime Adapter는 모델을 내려받지 않는다. 한글 경로에서는 검증된 모델을 ASCII 임시
경로에 복사하고 estimator 종료 후 복사본만 지운다.

브라우저 Gateway가 연결하는 private Eye HTTP worker는 저장소 루트에서 다음처럼 실행한다.
Eye 프로젝트는 의도적으로 package install을 하지 않으므로 `python -m mcm_eye.worker`를
저장소 루트에서 직접 실행하지 않는다.

```powershell
$env:EYE_FACE_MODEL_PATH = (Resolve-Path "services/eye/.cache/face_landmarker.task").Path
uv run --project services/eye --locked python services/eye/scripts/run_worker.py
```

카메라를 열지 않고 실행 경로만 확인하려면 `--check-imports`를 붙인다.

실제 카메라 데모는 화면에 보정점과 실시간 gaze crosshair만 표시한다. 카메라 frame,
이미지, landmark, 프레임별 gaze 좌표를 파일이나 로그에 남기지 않는다. Kiosk의 시간 기반
AOI 판정은 기존 `apps/kiosk/src/app/reaction-batch.ts`가 소유하며 다음 연결 작업에서 실제
`GazeSample`을 전달한다. 데모는 같은 원시 예측의 raw·stabilized valid 비율, jitter,
검증점 오차와 처리 지연만 집계한다. standalone 데모에는 기존 AOI Mapper를 복제하지
않으므로 AOI hit는 `null`이고 후속 Wiring에서 Mapper evaluator를 주입하면 계산된다.
jitter는 두 모드가 현재와 직전 frame에서 모두 유효한 동일한 frame pair만 양쪽에 함께
집계한다.
