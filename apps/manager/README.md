# Manager App

## 소유자

조윤혜가 화면을, 박형진이 API·polling 계약을 공동 소유한다.

## 로컬 실행

저장소 루트에서 다음 명령으로 실행한다.

```powershell
npm install
npm run dev:manager
```

기본 개발 주소는 `http://localhost:5174`이며 Backend·WebSocket 주소는 `.env.example`에서 확인한다.

## 입력

- 고객의 S04 제품 요청 `ManagerEvent`
- 이벤트 payload의 추천 Top 2 `product_id`와 상품 정보
- polling cursor 뒤의 이벤트 조회 결과

## 출력

- `view_recommended_products` 의도와 추천 Top 2가 포함된 제품 요청 알림 카드
- MVP에서 매니저가 확인한 착용·구매 `ConversionOutcome`

## 금지사항

- 원본 프레임, 얼굴 이미지, 얼굴 embedding을 수신하거나 표시하지 않는다.
- 고정 상품 QR 스캔만으로 특정 세션의 구매 전환을 확정하지 않는다.
- polling 재조회 시 동일 `event_id`를 새 이벤트로 중복 표시하지 않는다.
