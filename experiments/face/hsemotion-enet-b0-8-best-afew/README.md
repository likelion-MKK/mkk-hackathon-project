# HSEmotion enet_b0_8_best_afew 후보

## Inventory

| 항목 | 값 |
| --- | --- |
| 조사일 | 2026-08-13 |
| source | `https://github.com/av-savchenko/hsemotion` |
| source revision | `2546ff6fd09f911c0619354523293ff621b31ba2` |
| weight source revision | `520a051c64cd191521e5934655314e769a319684` |
| package | `hsemotion==0.3.0` |
| model ID | `enet_b0_8_best_afew` |
| runtime | Python, PyTorch local CPU |
| code license | Apache-2.0 |
| model asset | `enet_b0_8_best_afew.pt`, 로컬 `models/`에만 저장 |
| model SHA256 | `47c1423f3e6f50e3750bf7b0eda7db947c9ce0c2637e1766bf2187eddc652b17` |
| model size | 16,419,305 bytes |
| weight license | weight source repository의 Apache-2.0 |
| network | 최초 weight 다운로드 후 local asset 접근까지 확인 |
| Hard Gate | `fail` — 안전한 PyTorch 로더로 실행 불가 |

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
- 기존 파일과 새 다운로드 모두 PyTorch에 전달하기 전에 SHA256을 검증한다. 불일치하면 `model_checksum_mismatch`와 exit code `1`로 종료하며 pickle loader를 호출하지 않는다.

## Smoke 결과

Python 3.13.15에서 `hsemotion==0.3.0`, `torch==2.13.0`, `timm==1.0.28` 설치와 weight checksum 확인까지 성공했다.

```powershell
uv sync --locked
uv run python -m unittest -v test_smoke.py
uv run python smoke.py
uv run python smoke.py --offline
```

online과 offline 실행 모두 `unsafe_legacy_pickle_blocked`로 종료됐다. 배포 파일은 `timm.models.efficientnet.EfficientNet` 전체 객체를 pickle로 직렬화했으며 최신 PyTorch의 기본 `weights_only=True` 안전 로더가 이를 거부한다.

`weights_only=False`로 바꾸면 원격 pickle의 임의 코드 실행 가능성이 생기므로 사용하지 않았다. 안전한 `state_dict` 또는 ONNX 배포가 확인되지 않는 한 이 후보는 D4 benchmark와 production 선택 대상에서 제외한다.

Checksum 불일치는 자동으로 정상 weight처럼 교체하거나 로드하지 않는다. 로컬 `models/enet_b0_8_best_afew.pt`를 삭제하고 online smoke를 다시 실행해 고정 revision에서 재다운로드한다.
