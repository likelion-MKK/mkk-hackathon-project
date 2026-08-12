# Eye Service

## 소유자와 범위

양유상(PL·AI)이 소유한다. 웹캠 프레임에서 viewport 기준 point-of-gaze와 품질을 만들고, 캡처 시점 layout·영상 시각·AOI를 결합해 상품 hit 후보를 만드는 단계까지만 책임진다.

## 입력

- 수명 제한 메모리 프레임 참조와 캡처 시점 `FrameContext`
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

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.

## D1 Python scaffold

- 공통 타입과 `EyeAdapter` Protocol: `src/mcm_eye/contracts.py`
- 결정적 개발 Adapter: `src/mcm_eye/adapters/fake.py`
- 단위·Contract 호환 테스트: `tests/test_fake_adapter.py`

현재 Eye 환경은 `pyproject.toml`과 `uv.lock`에서 Python `3.13.15`로 고정한다. 실제 Eye
모델 후보가 호환되지 않으면 D1-03에 따라 근거를 ADR에 남기고 Eye 서비스 환경만 예외
버전으로 고정한다.

`FakeEyeAdapter.calibrate()`는 lifecycle과 `calibration_id` 전달을 검증하는 개발용
placeholder다. 실제 표적 좌표, 오차 측정, 재시도와 `gaze_unavailable` fallback은 D1-01의
D5 결정과 후속 Calibration 구현에서 다룬다.

`FakeEyeAdapter.infer()`는 입력 `FrameContext`의 `sequence`, `frame_id`, 캡처 시각을 항상
보존한다. 순서 역전 테스트는 `FakeGazeDelivery`가 인접한 두 샘플의 전달 순서만 바꾸며,
샘플 내부 필드는 수정하지 않는다.

```powershell
uv sync --locked
uv run pytest
```
