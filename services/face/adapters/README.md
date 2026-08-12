# Face Adapter Contract

이 문서는 특정 프로그래밍 언어, 라이브러리, 프로세스 또는 전송 방식에 종속되지 않는 논리 인터페이스다.

## 생명주기

- `metadata`: `adapter_id`, `model_id`, `model_revision`, `runtime`, `source_labels`, `taxonomy_version`을 반환한다.
- `initialize`: 고정된 설정으로 실행 자원을 준비한다.
- `warmup`: 첫 추론 지연을 서비스 시작 전에 처리한다.
- `infer`: 메모리 프레임 참조와 Kiosk가 소유한 `FrameContext` 중 `FaceFrameContext` Protocol에 필요한 필드를 받아 하나의 `ExpressionSample`을 만든다.
- `dispose`: 모델·버퍼 자원을 해제하되 Kiosk가 소유한 카메라를 임의로 다시 열지 않는다.

## 불변 조건

- `frame_id`, 캡처 시각과 영상 시각은 입력 `FrameContext`에서 이어받는다.
- score·quality 범위는 계약을 따르고, 대응 불가능한 label은 `unknown`으로 남긴다.
- no-face·multi-face·낮은 품질은 `valid`, `reason`, count로 구분한다.
- 원 모델 label과 공통 taxonomy의 mapping version을 결과에서 추적할 수 있어야 한다.
- 원본 프레임은 출력·예외·로그에 포함하지 않는다.

## 구현 슬롯

- [`fake/`](fake/README.md): 모델 없이 결정적인 개발·CI 신호를 만든다.
- [`replay/`](replay/README.md): 승인된 파생 JSON fixture를 재생한다.
- [`selected/`](selected/README.md): D5 선정 근거가 승인된 모델만 연결한다.
