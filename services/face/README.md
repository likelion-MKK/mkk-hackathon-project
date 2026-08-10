# Face Service

## 소유자와 범위

정은미(BE·Research/Dev)가 소유한다. 프레임에서 관찰 가능한 표정 관련 점수와 측정 품질을 만들고 후보별 label을 versioned 공통 taxonomy로 정규화하는 단계까지만 책임진다.

## 입력

- 수명 제한 메모리 프레임 참조와 캡처 시점 `FrameContext`
- 선택된 adapter 종류와 taxonomy mapping version

## 출력

- `face_detected`, `face_count`, score·quality를 가진 `ExpressionSample`
- `adapter_id`, 고정 `model_revision`, `taxonomy_version`

## 금지사항

- 점수를 실제 감정·성격·민감 특성 또는 구매 의도로 단정하지 않는다.
- no-face·timeout·unknown label을 중립 표정으로 대체하지 않는다.
- Eye 흐름을 기다리게 하거나 최종 추천 점수를 계산하지 않는다.
- 모델 코드·weight·대형 생성물을 이 scaffold에 넣지 않는다.

Adapter의 언어 독립 규약은 [`adapters/README.md`](adapters/README.md)를 따른다.
