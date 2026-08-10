# Eye Adapter Contract

이 문서는 특정 프로그래밍 언어, 라이브러리, 프로세스 또는 전송 방식에 종속되지 않는 논리 인터페이스다. 구현은 아래 동작과 이벤트 계약의 의미만 보존하면 된다.

## 생명주기

- `metadata`: adapter ID, 모델 ID·revision, runtime, calibration 가능 여부를 반환한다.
- `initialize`: 고정된 설정으로 실행 자원을 준비한다.
- `warmup`: 첫 추론 지연을 서비스 시작 전에 처리한다.
- `calibrate`: 필요한 구현만 화면 보정 결과와 `calibration_id`를 만든다.
- `infer`: 메모리 프레임 참조와 `FrameContext`를 받아 하나의 `GazeSample`을 만든다.
- `dispose`: 모델·버퍼 자원을 해제하되 Kiosk가 소유한 카메라를 임의로 다시 열지 않는다.

## 불변 조건

- 결과 시각과 `frame_id`는 입력 `FrameContext`에서 이어받는다.
- 유효 좌표는 viewport 기준 `0.0~1.0`이며 좌상단이 원점이다.
- 사용할 수 없는 결과는 `valid=false`와 구체적인 `reason`으로 표현한다.
- 모델 고유 landmark나 gaze vector는 adapter 밖의 공통 출력이 아니다.
- 원본 프레임은 출력·예외·로그에 포함하지 않는다.

## 구현 슬롯

- [`fake/`](fake/README.md): 모델 없이 결정적인 개발·CI 신호를 만든다.
- [`replay/`](replay/README.md): 승인된 파생 JSON fixture를 재생한다.
- [`selected/`](selected/README.md): D5 선정 근거가 승인된 모델만 연결한다.
