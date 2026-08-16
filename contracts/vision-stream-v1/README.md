# Vision Stream v1 계약

이 계약은 Kiosk 브라우저와 팀 관리 Vision Gateway 사이의 **일시적 binary WSS 경계**를 정의한다. 현재 [`ADR-0001`](../../docs/adr/0001-remote-vision-inference.md)이 `Proposed`이므로 실제 고객 frame 전송은 활성화하지 않으며, 계약과 합성 frame으로만 검증한다.

## 연결과 메시지 순서

1. 동의가 유효한 session은 `POST /api/v1/sessions/{session_id}/vision-stream-token`으로 1회용 단기 token을 받는다.
2. Kiosk는 같은 origin의 `/vision/v1/stream`에 WSS로 연결하고 첫 text message로 `hello`를 보낸다. token은 URL, log, APM에 기록하지 않는다.
3. Gateway는 token의 session/video binding, 만료, protocol version, encoding 교집합을 확인하고 `ready` 또는 `error` 후 `close`를 보낸다.
4. `ready` 전에 control이나 binary frame을 보내면 `protocol_error`다.
5. `start_calibration`은 Eye adapter가 필요할 때만 사용한다. 성공한 `control_result.calibration_id`는 이후 GazeSample에 보존한다.
6. `start_inference` 성공 이후에만 frame을 보낸다. 종료는 `stop_inference`, `stop_session`, 정상 close 순서다.

Text JSON은 [`vision-stream-message.schema.json`](vision-stream-message.schema.json), frame header는 [`vision-stream-frame-metadata.schema.json`](vision-stream-frame-metadata.schema.json)을 따른다. `ready.selected_frame_encoding`은 `hello.offered_frame_encodings` 중 하나여야 한다. `ready.limits` 값은 배포 환경이 협상하므로 예제의 4 FPS와 byte/timeout 값은 제품 상수가 아니다.

## Binary frame envelope

한 webcam frame은 한 WebSocket binary message로 전송한다. 네트워크 byte order는 big-endian이다.

| Offset | 길이 | 값 |
| --- | ---: | --- |
| 0 | 4 | ASCII magic `MCM1` |
| 4 | 4 | unsigned JSON header 길이 |
| 8 | N | UTF-8 JSON frame metadata, 최대 65,535 bytes |
| 8+N | 나머지 | 협상된 encoding의 image bytes |

`camera_frame.byte_length`는 binary suffix의 실제 길이와 같아야 한다. `camera_frame.width_px`, `height_px`, `encoding`은 webcam image 정보다. `layout`은 lookbook video가 viewport에 표시된 좌표이므로 두 정보를 섞지 않는다. JSON text, base64, data URI, multipart frame은 허용하지 않는다.

## Frame 수명과 flow control

- session별 in-flight frame은 정확히 1개다. 한 frame의 terminal message인 `result` 또는 `drop`을 받기 전에는 다음 frame을 전송하지 않는다.
- 캡처가 더 빨라 pending frame이 교체되면 아직 전송하지 않은 오래된 frame을 Kiosk가 즉시 `close()`한다. Gateway가 받지 않은 frame에는 `drop`을 기대하지 않는다.
- Gateway가 받은 모든 frame에는 정확히 하나의 `result` 또는 `drop`이 돌아온다. decode/inference 성공·실패와 무관하게 image buffer는 `finally`에서 해제한다.
- `(session_id, playback_epoch, frame_id)`는 frame key다. `sequence`는 session 안에서 단조 증가해야 한다. 중복, 감소한 sequence, 이전 epoch는 각각 `duplicate_frame`, `out_of_order`, `stale_epoch`로 drop한다.
- `result`와 내부 GazeSample/ExpressionSample의 7개 capture context 필드는 입력 metadata와 동일해야 한다: `session_id`, `video_id`, `frame_id`, `sequence`, `captured_at_mono_ms`, `video_time_ms`, `playback_epoch`.
- 현재 in-flight와 맞지 않는 late result는 Kiosk가 폐기한다. `playback_epoch`가 바뀌면 이전 epoch의 pending/in-flight 결과를 fusion에 사용하지 않는다.

## Timeout, error, close

Frame별 제한은 `ready.limits`를 적용한다. decode timeout은 `drop/decode_timeout`, inference deadline 초과는 `drop/inference_timeout`이며 둘 다 해당 frame의 terminal message다. 과부하와 frame 크기 제한도 가능한 경우 `drop`으로 응답한 뒤 연결을 유지한다.

연결·control 수준 문제는 `error`로 알린다. `network_unavailable`은 서버가 보낼 수 없는 client-side 정규화 코드이며, 연결 실패나 사전 `close` 통지 없는 비정상 종료를 Kiosk가 이 코드로 매핑한다. live 오류를 Fake 결과로 자동 대체하지 않는다.

| WebSocket code | close reason | 의미 |
| ---: | --- | --- |
| 1000 | `normal` | `stop_session` 완료 |
| 1002 | `protocol_error` | envelope·순서·JSON 위반 |
| 1008 | `unauthorized` | token/session/video 정책 위반 |
| 1009 | `frame_too_large` | 협상된 최대 frame 크기 위반 |
| 1011 | `vision_unavailable` | Vision runtime 사용 불가 |
| 1013 | `server_overloaded` | 일시적 과부하 |

Gateway는 가능한 경우 JSON `close`를 먼저 보내고 같은 code로 WebSocket close frame을 보낸다. close reason에는 token, 원본 경로, 모델 stack trace 같은 민감 정보를 넣지 않는다.

## 개인정보 경계

원본 frame은 Kiosk/Gateway/Worker의 현재 처리 메모리에만 존재한다. REST/event, 파일, DB, cache, queue, log, APM, browser storage에 image bytes·base64·얼굴 embedding·원본 경로를 남기지 않는다. Gateway 밖 Backend와 중앙 AI에는 기존 파생 `GazeSample`, `ExpressionSample`, `FrameObservationV2`만 전달한다.
