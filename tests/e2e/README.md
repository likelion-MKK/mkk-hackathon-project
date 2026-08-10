# End-to-End Tests

## 소유와 입력

조윤혜가 사용자 흐름을, 박형진이 API·DB·Manager 경계를 주도하고 전원이 Gate에서 확인한다. Fake/Replay Adapter, mock 추천, 테스트 상품·QR을 기본 입력으로 사용한다.

## 검증 결과

S01→S04, 동의·취소·timeout, 카메라 거부, 데이터 부족, 네트워크 단절, Top 2·QR, Manager 알림·재연결, conversion 입력과 clean session reset을 검증한다.

## 금지사항

Mock 추천을 실제 추천으로 표시하지 않으며, E2E 성공을 실제 모델 정확도나 알고리즘 품질의 증거로 사용하지 않는다.
