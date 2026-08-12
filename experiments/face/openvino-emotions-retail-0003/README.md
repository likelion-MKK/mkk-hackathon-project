# OpenVINO emotions-recognition-retail-0003 후보

## Inventory

| 항목 | 값 |
| --- | --- |
| 조사일 | 2026-08-13 |
| source | `https://github.com/openvinotoolkit/open_model_zoo` |
| source revision | tag `2023.3.0`, commit `cf08c4915cde7513bc1970484a8901ac37df8283` |
| package | `openvino==2026.3.0` |
| runtime | Python, OpenVINO local CPU |
| code license | Apache-2.0 |
| model asset | FP32 XML·BIN, 로컬 `models/`에만 저장 |
| model checksum | 공식 manifest의 SHA-384와 로컬 SHA256을 함께 확인 예정 |
| weight license | Open Model Zoo manifest가 지정한 Apache-2.0 |
| network | 최초 XML·BIN 다운로드에만 필요, 추론은 local-only 검증 예정 |
| Hard Gate | `pending` |

## 입력과 출력

- 입력: `1×3×64×64` BGR face crop
- 전처리: 코드에서 생성한 고정 `float32` tensor
- 출력: `neutral`, `happy`, `sad`, `surprise`, `anger` 순서의 5개 softmax 값

이 label은 모델이 관찰한 분류 점수이며 실제 감정이나 구매 의도의 확정값으로 사용하지 않는다.

## 잠정 taxonomy mapping

| 원본 label | 잠정 label |
| --- | --- |
| `neutral` | `neutral_like` |
| `happy` | `happy_like` |
| `sad` | `sad_like` |
| `surprise` | `surprise_like` |
| `anger` | `anger_like` |

잠정 mapping은 D4 비교 대상이며 Contract나 production taxonomy를 변경하지 않는다.

## 알려진 제한과 확인 항목

- 문서상 정면 얼굴, yaw·pitch 약 ±15도와 최소 64px 얼굴을 대상으로 한다.
- Open Model Zoo는 maintenance mode이므로 장기 유지보수 위험을 기록한다.
- Python 3.13.15 설치, FP32 모델 로딩, 출력 shape와 offline 재실행을 smoke에서 확인한다.

## Smoke 결과

`not_run`. 실행 명령, checksum, 결과와 실패 원인은 smoke 구현 후 이 문서에 기록한다.
