# Applications

사용자·매장 운영자·백엔드 진입점을 모으는 영역이다. 앱은 `contracts/`의 공개 계약만 사용하며 Eye/Face 모델 구현을 직접 참조하지 않는다.

- `kiosk/`: 조윤혜 소유. S01-S04, 영상·웹캠 orchestration과 화면 상태를 담당한다.
- `manager/`: 조윤혜(UI)와 박형진(API 계약) 공동 소유. 매장 알림과 전환 결과 입력을 담당한다.
- `api/`: 박형진 소유. FastAPI, PostgreSQL 경계, 추천·QR·알림 API를 담당한다.

## 공통 금지사항

- 원본 웹캠 프레임을 파일·DB·로그·HTTP/WebSocket payload로 남기지 않는다.
- 앱 안에 특정 Eye/Face 모델의 전처리·추론·label 변환 코드를 넣지 않는다.
- 계약 변경을 앱 기능 변경과 같은 PR에서 처리하지 않는다.
- Mock 결과를 실제 추천 결과처럼 표시하지 않는다.
