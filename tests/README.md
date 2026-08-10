# Tests

테스트는 원본 얼굴 미디어 대신 비식별 파생 fixture를 사용한다.

- `contract/`: schema와 producer/consumer 호환성
- `integration/`: 앱·서비스·API 사이 연결
- `replay/`: 시간·결측·지연 scenario의 결정적 재생
- `e2e/`: S01-S04와 Manager 사용자 흐름

무거운 실제 모델 benchmark는 일반 PR test와 분리해 수동 또는 scheduled lane에서 실행한다.
