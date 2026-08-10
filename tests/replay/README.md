# Replay Tests

## 소유와 입력

양유상·정은미가 각 신호 fixture를, 박형진이 세션 harness를 관리한다. 승인된 파생 이벤트와 virtual/replay clock만 사용한다.

## 검증 결과

정상 시선, 고정·이동·겹침 AOI, 화면 밖, low-confidence, no/multi-face, 지연·순서 역전, pause·seek·replay, 중복 batch와 신호 부족 session을 같은 입력에서 결정적으로 재현한다.

## 금지사항

실제 얼굴 영상·이미지·base64를 fixture로 쓰지 않고, 결측값을 임의의 정상값으로 보정하지 않는다.
