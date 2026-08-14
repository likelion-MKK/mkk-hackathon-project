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

- 머문 시간, 재시선 가중치, 최종 관심 점수나 Top 2를 계산하지 않는다.
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
placeholder다. `EyeTraxAdapter`는 현재 룩북 전용 Dense5 학습과 별도 8점 검증을 최대 두
번 수행한다. 각 검증점은 전체 frame을 최소 15개 제공해야 하며, 부족하면 정확도 수치와
무관하게 Gate 실패로 처리한다. 보정 요청 전 추론은 lifecycle 오류이며, 보정 중이거나
최종 실패한 뒤에는 현재 `calibration_id`로 `valid=false`, `reason=gaze_unavailable`을
반환한다.

EyeTrax가 유효 좌표를 만들면 `confidence=1.0`을 사용한다. 이 값은 정확도 100%가 아니라
해당 frame에서 사용할 수 있는 좌표라는 이진 표시다. `no_face`, `blink`, 비유효한 예측과
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

실제 카메라 데모는 화면에 보정점과 실시간 gaze crosshair만 표시한다. 카메라 frame,
이미지, landmark, 프레임별 gaze 좌표를 파일이나 로그에 남기지 않는다. Kiosk의 시간 기반
AOI 판정은 기존 `apps/kiosk/src/app/reaction-batch.ts`가 소유하며 다음 연결 작업에서 실제
`GazeSample`을 전달한다. 데모는 같은 원시 예측의 raw·stabilized valid 비율, jitter,
검증점 오차와 처리 지연만 집계한다. standalone 데모에는 기존 AOI Mapper를 복제하지
않으므로 AOI hit는 `null`이고 후속 Wiring에서 Mapper evaluator를 주입하면 계산된다.
jitter는 두 모드가 현재와 직전 frame에서 모두 유효한 동일한 frame pair만 양쪽에 함께
집계한다.
