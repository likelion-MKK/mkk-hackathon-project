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

Face 패키지는 Kiosk의 구체적인 `FrameContext` 타입을 소유하지 않는다. Kiosk가 만든 객체가 공개 `FaceFrameContext` Protocol의 필드를 제공하면 구조적으로 호환된다. `frame`은 동일 Kiosk 메모리 안의 수명 제한 참조이며 Adapter 결과·예외·로그에 포함하지 않는다.

## 입력

- 수명 제한 메모리 프레임 참조와 캡처 시점 `FrameContext`
- 선택된 adapter 종류와 taxonomy mapping version

## 출력

- `face_detected`, `face_count`, score·quality를 가진 `ExpressionSample`
- `adapter_id`, 고정 `model_revision`, `taxonomy_version`

## 금지사항

- 점수를 실제 감정·성격·민감 특성 또는 구매 의도로 단정하지 않는다.
- no-face·timeout·unknown label을 중립 표정으로 대체하지 않는다.
- Eye 흐름을 기다리게 하거나 최종 추천 점수를 계산하지 않는다.
- 모델 코드·weight·대형 생성물을 이 scaffold에 넣지 않는다.

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.
