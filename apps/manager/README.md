# Manager App

## 소유자

조윤혜가 화면을, 박형진이 API·WebSocket 계약을 공동 소유한다.

## 로컬 실행

저장소 루트에서 다음 명령으로 실행한다.

```powershell
npm install
npm run dev:manager
```

기본 개발 주소는 `http://localhost:5174`이며 Backend·WebSocket 주소는 `.env.example`에서 확인한다.

## 입력

- 사용 시작·추천 완료 `ManagerEvent`
- 세션별 `RecommendationResult`와 상품 정보
- WebSocket 재연결 뒤 누락 복구용 이벤트 조회 결과

## 출력

- 세션 카드의 상태와 Top 2 갱신
- MVP에서 매니저가 확인한 착용·구매 `ConversionOutcome`

## 금지사항

- 원본 프레임, 얼굴 이미지, 얼굴 embedding을 수신하거나 표시하지 않는다.
- 고정 상품 QR 스캔만으로 특정 세션의 구매 전환을 확정하지 않는다.
- WebSocket 재연결 시 동일 `event_id`를 새 이벤트로 중복 표시하지 않는다.
