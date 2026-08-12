# Services

모델·AOI·추천처럼 앱에서 교체 가능한 도메인 로직의 경계다. 서비스끼리는 공개 이벤트 계약으로 연결한다. 원격 추론이 승인되면 Vision Gateway가 WSS frame을 메모리에서 decode하고 Eye·Face Worker에는 같은 서버 trust boundary 안의 수명 제한 메모리 참조만 전달한다.

- `eye/`: 양유상 소유. point-of-gaze, 품질, 좌표 변환과 AOI hit 후보까지 담당한다.
- `face/`: 정은미 소유. 관찰 가능한 표정 점수, 품질과 taxonomy 정규화를 담당한다.
- `recommendation/`: 박형진 소유. 파생 신호 집계와 Top 2 결과 경계를 담당한다.

서비스는 다른 영역의 내부 구현을 import하지 않으며, 모델 선정 전에는 Fake/Replay Adapter를 기본 통합 수단으로 사용한다.

원격 실행 경계는 [`ADR-0001`](../docs/adr/0001-remote-vision-inference.md)을 따른다. Adapter 출력·예외·로그에는 원본 frame을 포함하지 않고 일반 FastAPI·PostgreSQL로 전달하지 않는다.
