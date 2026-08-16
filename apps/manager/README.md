# Manager App

## 소유자

조윤혜가 화면을, 박형진이 API·polling 계약을 공동 소유한다.

## 로컬 실행

저장소 루트에서 다음 명령으로 실행한다.

```powershell
npm install
npm run dev:manager
```

기본 개발 주소는 `http://localhost:5174`이다. Backend 주소와 선택적 개발 proxy는
`.env.example`에서 확인한다. Manager MVP는 WebSocket을 사용하지 않고 REST polling만
사용한다.

## 입력

- 고객의 S04 제품 요청 `ManagerEventV2`
- 이벤트 payload의 v2 Top 1 `selected_product_id`와 상품 정보
- polling cursor 뒤의 이벤트 조회 결과

## 출력

- `view_recommended_product` 의도와 Top 1 상품이 포함된 제품 요청 알림 카드
- 고객이 Kiosk S04에서 명시적으로 요청한 이벤트만 표시

기존 v1 Top 2 endpoint와 fixture는 Backend 호환성 범위로만 유지하며 Manager MVP는
v2 event와 상품 endpoint만 읽는다. 구매·호감과 `ConversionOutcome`은 후속 확장
계약이며 MVP 화면·추천·학습에는 사용하지 않는다.

## 금지사항

- 원본 프레임, 얼굴 이미지, 얼굴 embedding을 수신하거나 표시하지 않는다.
- 고객 요청 없이 세션 시작이나 추천 완료만으로 알림을 자동 생성하지 않는다.
- 고정 상품 QR 스캔만으로 특정 세션의 구매 전환을 확정하지 않는다.
- polling 재조회 시 동일 `event_id`를 새 이벤트로 중복 표시하지 않는다.
