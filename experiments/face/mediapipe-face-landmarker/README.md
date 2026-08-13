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
| model asset | `face_landmarker.task` version `1`, 다운로드 후 로컬 `models/`에만 저장 |
| model URL | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` |
| model SHA256 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` |
| model size | 3,758,596 bytes |
| weight license | Apache-2.0 — 구성 모델 3종의 공식 model card에서 확인 |
| network | 최초 asset 다운로드에만 필요, 이후 local asset buffer로 재실행 성공 |
| Hard Gate | `pass` — 고정 URL·SHA256과 code·weight license 확인 |

## License 근거

[공식 Face Landmarker 문서](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/index)는 `face_landmarker.task`가 BlazeFace Short Range, FaceMesh V2, Blendshape 모델로 구성된다고 설명한다. 각 구성 모델의 공식 model card는 Apache License 2.0을 명시한다.

- [BlazeFace Short Range model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf)
- [FaceMesh V2 model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf)
- [Blendshape V2 model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf)
- [Apache License 2.0 원문](https://www.apache.org/licenses/LICENSE-2.0)

Apache-2.0에 따라 상업적 사용·수정·재배포가 가능하다. 모델을 배포할 때는 라이선스 사본을 제공하고 기존 저작권·특허·상표·귀속 고지를 유지하며, 배포물에 `NOTICE`가 있으면 해당 고지를 함께 제공한다. 이 D2 PR에는 model weight를 포함하지 않으며, 향후 제품 패키징 시 라이선스·NOTICE 준수를 별도로 검증한다.

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
- 공식 예제의 immutable version `1` URL과 SHA256을 함께 고정한다.
- Python 3.13.15 wheel, no-face 처리, offline 재실행을 smoke에서 확인한다.
- 기존 파일과 새 다운로드 모두 모델을 읽기 전에 SHA256을 검증한다. 불일치하면 `model_checksum_mismatch`와 exit code `1`로 종료하며 모델 runtime을 초기화하지 않는다.

## Smoke 결과

Python 3.13.15에서 package 설치, synthetic no-face 입력 추론과 local-only 재실행이 통과했다.

```powershell
uv sync --locked
uv run python -m unittest -v test_smoke.py
uv run python smoke.py
uv run python smoke.py --offline
```

두 실행 모두 `face_count=0`, `blendshape_groups=0`, `status=pass`를 반환했다. Windows의 한글 경로를 native runtime에 직접 전달하면 asset을 열지 못하므로, 같은 로컬 파일을 `model_asset_buffer`로 읽어 경로 의존성을 제거했다.

Checksum 불일치는 자동으로 정상 asset처럼 교체하거나 로드하지 않는다. 로컬 `models/face_landmarker.task`를 삭제하고 online smoke를 다시 실행해 고정 URL에서 재다운로드한다.

Smoke와 license Hard Gate 통과는 D4 동일 조건 benchmark 진입이 가능하다는 뜻이며, 52개 blendshape 품질이나 production 모델 선정을 의미하지 않는다. 최종 선택은 D5 benchmark·ADR 승인 이후에만 진행한다.
