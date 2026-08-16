# Contract Tests

## 소유와 입력

박형진이 계약 test harness를 관리하고, 변경 영향을 받는 Eye·Face·FE 소유자가 fixture를 함께 리뷰한다. 입력은 `contracts/`의 schema·OpenAPI와 정상·오류·경계 예제다.

## 검증 결과

Fake/Replay/Selected Adapter와 producer/consumer가 같은 version·필수 필드·유효성 의미를 지키는지 판정한다. raw frame/base64 필드가 공개 계약에 생기지 않았는지도 검사한다.

## 금지사항

특정 언어의 내부 타입만 검사해 공개 JSON 계약 검증을 대신하지 않으며, 깨지는 계약 변경을 기능 PR에 숨기지 않는다.

## Vision Stream v1

`test_vision_stream_v1.py`는 실제 영상 파일 없이 runtime에서 synthetic bytes를 만들고 binary envelope의 magic, header 길이, payload 길이와 capture context 보존을 검증한다. 실제 고객 frame이나 image fixture는 사용하지 않는다.
