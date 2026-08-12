# MediaPipe Face Landmarker 후보

## Inventory

| 항목 | 값 |
| --- | --- |
| 조사일 | 2026-08-13 |
| source | `https://github.com/google-ai-edge/mediapipe` |
| source revision | `493c90e5f3eb40b9080606964fc18528a99962f0` |
| package | `mediapipe==1.0.0` |
| runtime | Python, local CPU |
| code license | Apache-2.0 |
| model asset | `face_landmarker.task`, 다운로드 후 로컬 `models/`에만 저장 |
| model SHA256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| model size | 3,758,596 bytes |
| weight license | 공식 model card와 배포 조건 확인 중 |
| network | 최초 asset 다운로드에만 필요, 이후 local asset buffer로 재실행 성공 |
| Hard Gate | `pending` — 명시적인 weight license 확인 전 D4 비교 제외 |

## 입력과 출력

- 입력: 코드에서 생성한 고정 RGB `uint8` 이미지
- 전처리: MediaPipe `Image`로 변환
- 출력: 얼굴 landmark와 52개 blendshape 계수
- synthetic no-face 입력의 예상 결과: 빈 face landmark·blendshape 목록

이 후보의 blendshape는 관찰 가능한 얼굴 동작 계수다. 실제 감정·성격·구매 의도로 해석하지 않는다.

## 잠정 taxonomy mapping

- 원본 blendshape 이름을 snake_case의 관찰 신호로 보존한다.
- `mouthSmileLeft`와 `mouthSmileRight`처럼 좌우 값은 D4에서 별도 유지와 집계 방식을 비교한다.
- 공통 taxonomy로 확정되지 않은 항목은 `unknown`으로 남긴다.

## 알려진 제한과 확인 항목

- front-facing camera와 얼굴 가시성에 민감하다.
- model URL의 `latest` 별칭은 변경될 수 있으므로 실제 사용 파일의 SHA256을 고정해야 한다.
- Python 3.13.15 wheel, no-face 처리, offline 재실행을 smoke에서 확인한다.

## Smoke 결과

Python 3.13.15에서 package 설치, synthetic no-face 입력 추론과 local-only 재실행이 통과했다.

```powershell
uv sync --locked
uv run python smoke.py
uv run python smoke.py --offline
```

두 실행 모두 `face_count=0`, `blendshape_groups=0`, `status=pass`를 반환했다. Windows의 한글 경로를 native runtime에 직접 전달하면 asset을 열지 못하므로, 같은 로컬 파일을 `model_asset_buffer`로 읽어 경로 의존성을 제거했다.

Smoke 통과는 52개 blendshape 품질을 검증하지 않는다. D4 진입 전 weight license를 명시적으로 확인해야 한다.
