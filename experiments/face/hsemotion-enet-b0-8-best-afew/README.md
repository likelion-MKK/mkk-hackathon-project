# HSEmotion enet_b0_8_best_afew 후보

## Inventory

| 항목 | 값 |
| --- | --- |
| 조사일 | 2026-08-13 |
| source | `https://github.com/av-savchenko/hsemotion` |
| source revision | `2546ff6fd09f911c0619354523293ff621b31ba2` |
| package | `hsemotion==0.3.0` |
| model ID | `enet_b0_8_best_afew` |
| runtime | Python, PyTorch local CPU |
| code license | Apache-2.0 |
| model asset | `enet_b0_8_best_afew.pt`, 로컬 `models/`에만 저장 |
| model SHA256 | smoke 실행 후 기록 |
| weight license | 명시적인 별도 weight license 확인 중 |
| network | 최초 weight 다운로드에만 필요, 추론은 local-only 검증 예정 |
| Hard Gate | `pending` |

## 입력과 출력

- 입력: 코드에서 생성한 고정 RGB face crop
- 전처리: `224×224`, ImageNet normalize
- 출력: `Anger`, `Contempt`, `Disgust`, `Fear`, `Happiness`, `Neutral`, `Sadness`, `Surprise` 8개 점수

분류 이름은 모델 원본 label일 뿐 실제 감정·성격·구매 의도를 확정하지 않는다.

## 잠정 taxonomy mapping

원본 이름을 소문자로 바꾸고 `_like`를 붙인 관찰 점수로만 검토한다. 의미가 공통 taxonomy와 일치한다고 확인할 수 없는 label은 `unknown`으로 남긴다.

## 알려진 제한과 확인 항목

- package가 weight를 사용자 홈의 `.hsemotion`에 자동 다운로드하므로 smoke에서는 ignored `models/`로 경로를 격리한다.
- code license와 model weight license가 동일하다고 가정하지 않는다.
- Python 3.13.15·PyTorch 호환성, 고정 revision 재현성, weight license와 offline 재실행을 확인한다.

## Smoke 결과

`not_run`. 실행 명령, checksum, 결과와 실패 원인은 smoke 구현 후 이 문서에 기록한다.
