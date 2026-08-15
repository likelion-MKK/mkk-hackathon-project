# Face Service

## 소유자와 범위

정은미(BE·Research/Dev)가 소유한다. 프레임에서 관찰 가능한 표정 관련 점수와 측정 품질을 만들고 후보별 label을 versioned 공통 taxonomy로 정규화하는 단계까지만 책임진다.

## 개발 환경과 검증

Face 서비스는 저장소의 다른 Python 영역과 분리된 Python `3.13.15`와 `uv` 환경을 사용한다.

```powershell
Set-Location services/face
uv sync --locked
uv run pytest
```

Contract 전체 검증은 저장소 루트에서 실행한다.

```powershell
python scripts/validate_contracts.py
```

기본 실행 모드는 `fake`다. 실제 모델은 명시적으로 `MCM_FACE_MODE=selected`와
`MCM_FACE_MODEL_PATH`를 설정한 경우에만 선택한다. `replay`는
`MCM_FACE_REPLAY_FIXTURE`가 필요하다. 이 실행 선택은 실제 결과와 mock 추천 결과를
섞지 않으며 Face Worker는 추천 결과를 생성하지 않는다.

## D6 Selected Adapter와 Worker

`SelectedFaceAdapter`는 ADR-0003의 MediaPipe Face Landmarker 설정을 사용한다.
모델은 `mediapipe==1.0.0`, asset revision `face_landmarker/float16/1`, SHA256
`64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`로 검증한 뒤
메모리에서 연다. `output_face_blendshapes=true`, `num_faces=2`이며 얼굴이 정확히
하나일 때만 valid다.

동일한 전체 `FaceFrameContext` 재호출은 TTL이 있는 bounded LRU에서 canonical
`ExpressionSample`을 재사용해 모델을 다시 실행하지 않는다. cache에는 frame,
landmark와 원본 blendshape를 넣지 않으며, 원문 context tuple 대신 전체 context로 만든
결정적 `event_id` digest를 cache key로 사용해 원문 session ID를 key에 보관하지 않는다.
cache는 최초 initialize, TTL 만료와 dispose 경계에서 정리한다. MediaPipe landmark의
`presence`/`visibility` 품질 channel이 완전하게
제공되지 않으면 quality를 임의 추정하지 않고 `low_quality`로 fail-closed 처리한다.

카메라 기능은 기본 테스트 의존성에서 분리되어 있다.

```powershell
Set-Location services/face
uv sync --locked --extra camera
```

모델 weight는 Git에 넣지 않는다. 기존 후보 실험의 고정 URL·checksum 절차로 받은
`face_landmarker.task`의 경로를 smoke 명령에 직접 전달한다.

## 실제 카메라 smoke test

다음 명령은 개발자가 실제 video 장치와 모델을 준비한 로컬 환경에서만 실행한다.
자동 테스트와 CI에서는 실행하지 않는다. OpenCV video capture만 열며 audio 장치를
요청하는 코드가 없다.

```powershell
Set-Location services/face
uv run --extra camera camera-smoke-test --model-path ../../experiments/face/mediapipe-face-landmarker/models/face_landmarker.task --device 0 --width 640 --height 480 --fps 5 --frames 30
```

출력 JSON에는 장치 목록, permission 상태, 요청/실제 width·height·fps, 최신 face
count, no-face/multi-face 비율, 평균·최대 처리 지연, timeout/error 횟수만 포함된다.
frame·landmark·원본 blendshape·image bytes·base64는 출력·로그·파일·DB에 쓰지 않는다.
세션 종료와 오류 경로 모두 camera release, worker executor 종료, 모델 dispose를
실행한다.

카메라 권한·장치·구도를 눈으로 확인해야 할 때는 로컬 개발 전용 preview를 명시적으로
실행한다. 이 명령은 Face 추론이나 추천 결과를 표시하지 않으며, video frame을 화면에
보여주는 동안의 메모리 밖에 저장하거나 전송하지 않는다. `Q` 또는 `Esc`로 종료한다.

```powershell
uv run --extra camera camera-preview --device 0 --width 640 --height 480
```

preview는 자동 테스트와 CI에서 실행하지 않는다. 운영 Kiosk의 카메라 화면·권한 UX는
`apps/kiosk`와 D8 live gate의 별도 책임이다.

운영 브라우저의 권한 UX, WSS Gateway, 실제 Kiosk-to-server 지연, 현장 품질 threshold,
장시간·동시 세션과 worker process 강제 재시작은 D8 live gate에서 검증한다.

## Fake Adapter 사용

`FakeFaceAdapter`는 실제 카메라·모델·weight·네트워크 없이 결정적인 `ExpressionSample`을 만든다. 지원 scenario는 `valid_face`, `no_face`, `multi_face`, `unknown_label`, `low_quality`, `timeout`이다.

```python
from dataclasses import dataclass

from mcm_face import FakeFaceAdapter


@dataclass(frozen=True, slots=True)
class KioskFrameContext:
    session_id: str
    sequence: int
    frame_id: str
    captured_at_mono_ms: float
    video_id: str
    video_time_ms: int
    playback_epoch: int

adapter = FakeFaceAdapter(seed=7, scenario="valid_face")
adapter.initialize()
adapter.warmup()

sample = adapter.infer(
    frame=object(),
    context=KioskFrameContext(
        session_id="session-demo-001",
        sequence=1,
        frame_id="frame-0001",
        captured_at_mono_ms=1234.5,
        video_id="lookbook-demo-v1",
        video_time_ms=4200,
        playback_epoch=0,
    ),
)

payload = sample.to_payload()
adapter.dispose()
```

Face 패키지는 Kiosk의 구체적인 `FrameContext` 타입을 소유하지 않는다. Kiosk가 만든 capture context가 공개 `FaceFrameContext` Protocol의 필드를 제공하면 구조적으로 호환된다. 원격 추론에서는 Vision Gateway가 decode한 `frame`을 같은 서버 trust boundary의 수명 제한 메모리 참조로 전달하며 Adapter 결과·예외·로그에 포함하지 않는다.

## Replay Adapter 사용

`ReplayFaceAdapter`는 원본 미디어 대신 JSON fixture의 파생 관측값을 순서대로 재생한다. fixture record에는 `face_detected`, `face_count`, `scores`, `quality`, `valid`, `confidence`, `reason`만 저장한다. 세션·프레임·영상 시간 필드는 매 `infer` 호출의 `FaceFrameContext`에서 가져온다.

```python
from pathlib import Path

from mcm_face import ReplayFaceAdapter


adapter = ReplayFaceAdapter.from_fixture(
    Path("tests/fixtures/expression-replay.d3.json")
)
adapter.initialize()
adapter.warmup()

sample = adapter.infer(frame=frame_reference, context=kiosk_frame_context)
payload = sample.to_payload()

adapter.dispose()
```

처음 보는 `FaceFrameContext`의 `infer`만 record 하나를 소비한다. 같은 context를 재시도하면 Adapter가 이미 만든 `ExpressionSample`과 동일한 `event_id`를 반환하며 cursor를 진행하지 않는다. `event_id`는 downstream 재전송 중복 제거 키로 사용한다. 마지막 record 이후 처음 보는 context에는 자동 순환 없이 `ReplayExhaustedError`를 발생시키지만, 이미 처리한 context의 재시도는 계속 같은 결과를 반환한다. 실행 중 반복 `initialize`는 cursor와 재시도 cache를 유지하며, `dispose` 후 다시 초기화하면 둘을 비우고 첫 record부터 재생한다. cache에는 파생 `ExpressionSample`만 저장하며 frame은 저장하지 않는다.

Replay의 no-face는 정상·중립 표정이 아니다. `face_detected=false`, `face_count=0`, `valid=false`, 빈 `scores`, `reason=no_face`인 관측 실패 이벤트로 그대로 전달한다. 영상 pause·seek·replay 시 Kiosk가 증가시킨 `playback_epoch`과 캡처 순간의 `video_time_ms`를 수정하지 않으므로, epoch이 바뀌었다면 영상 시간이 감소해도 그대로 보존한다.

Fixture 형식과 검증·개인정보 규칙은 [`adapters/replay/README.md`](adapters/replay/README.md)를 따른다.

## 입력

- Vision Gateway가 decode한 수명 제한 서버 메모리 frame 참조와 Kiosk 캡처 시점 `FrameContext`
- 선택된 adapter 종류와 taxonomy mapping version

## 출력

- `face_detected`, `face_count`, score·quality를 가진 `ExpressionSample`
- `adapter_id`, 고정 `model_revision`, `taxonomy_version`

## 금지사항

- 점수를 실제 감정·성격·민감 특성 또는 구매 의도로 단정하지 않는다.
- no-face·timeout·unknown label을 중립 표정으로 대체하지 않는다.
- Eye 흐름을 기다리게 하거나 최종 추천 점수를 계산하지 않는다.
- 모델 코드·weight·대형 생성물을 이 scaffold에 넣지 않는다.
- 원본 frame을 Adapter 출력·예외·로그·파일·DB·cache에 포함하지 않는다.

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.
