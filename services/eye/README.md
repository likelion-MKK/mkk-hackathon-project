# Eye Service

## 소유자와 범위

양유상(PL·AI)이 소유한다. 웹캠 프레임에서 viewport 기준 point-of-gaze와 품질을 만들고, 캡처 시점 layout·영상 시각·AOI를 결합해 상품 hit 후보를 만드는 단계까지만 책임진다.

## 입력

- 수명 제한 메모리 프레임 참조와 캡처 시점 `FrameContext`
- 화면·영상 layout과 version이 고정된 `LookbookManifest`
- 선택된 adapter 종류와 calibration 설정

## 출력

- viewport 정규화 좌표와 품질을 가진 `GazeSample`
- 영상 좌표 변환·time-aware AOI 판정 뒤의 `ProductAttentionEvent`
- `adapter_id`, 고정 `model_revision`, calibration·manifest version

## 금지사항

- 머문 시간, 재시선 가중치, 최종 관심 점수나 Top 2를 계산하지 않는다.
- 무효 시선을 `(0, 0)`으로 만들거나 영상 밖 시선을 임의의 상품에 연결하지 않는다.
- 추론 완료 시점의 영상 시각을 사용하지 않는다.
- 모델 코드·weight·대형 생성물을 이 scaffold에 넣지 않는다.

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.
