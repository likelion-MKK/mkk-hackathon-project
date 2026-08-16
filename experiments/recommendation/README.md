# Central Recommendation A/B/C Evaluation

이 디렉터리는 중앙 추천 AI의 model을 다운로드하거나 호출하지 않고도 contract, Korean system prompt, 최소 model payload와 grounding gate를 반복 검증하는 실험 경계입니다. 표정·시선은 관찰 가능한 세션 신호일 뿐 심리·감정 진단 학습 데이터가 아닙니다.

## 고정된 비교안

| Variant | Model에 전달하는 evidence | 목적 |
| --- | --- | --- |
| A | summary + evidence windows + timeline | 가장 많은 저수준 맥락 |
| B | timeline + summary | window 없이 frame-level 신호만 비교 |
| C | summary + evidence windows | timeline을 제거한 최소 맥락 |

세 variant는 동일한 fixture, 10개 catalog, prompt/version, generation 설정과 target server에서 비교해야 합니다. Builder는 catalog의 URL·image·QR source metadata를 model payload에서 제거하고 선택에 필요한 ID, 이름, controlled tag, 팀 작성 summary와 style만 전달합니다.

내부 `RecommendationEvidenceV2`는 strict contract 때문에 absent block도 명시적 `null`로 보존하지만, model에 serialize할 때는 absent key를 제거합니다. 따라서 실제 key 순서는 A `summary→evidence_windows→timeline`, B `timeline→summary`, C `summary→evidence_windows`입니다. A/C decision은 `{kind=window,ref_id=window_id}`, B decision은 `{kind=frame,ref_id=frame_id}`만 참조합니다. B의 frame은 attention candidate가 선택 상품인 경우만 근거가 되며 Backend가 보이지 않은 window ID를 추측해 채우지 않습니다.

## 실행

저장소 루트에서 contract 의존성을 사용합니다.

```powershell
uv run --with-requirements requirements-contracts.txt python experiments/recommendation/evaluate_variants.py --validate-only
uv run --with-requirements requirements-contracts.txt python experiments/recommendation/evaluate_variants.py --emit-variant C
```

첫 명령은 다음을 실제로 검증합니다.

- Draft 2020-12 v2 profile/evidence/decision schema
- 정확히 10개이고 중복 없는 reviewed team product ID
- A/B/C의 window/timeline 포함 규칙
- model payload의 raw image/frame, data URI, embedding, landmark, original/source path 금지
- Top 1 catalog membership, controlled tag와 evidence window reference grounding
- benchmark 전 model 미선정 상태

`results/model-benchmark-status.v1.json`은 현재 `status=not_run`, `reason=no_local_gpu`입니다. 이 workspace에는 HF token과 NVIDIA GPU가 없으므로 Qwen/Mistral inference, 지연, VRAM 또는 정확도 결과를 실행했다고 간주하지 않습니다. 외부 provider도 self-hosted 경계를 지키기 위해 사용하지 않습니다. Weight를 내려받지 않았으므로 registry의 checksum은 `null`, status는 `not_collected_model_not_downloaded`입니다. 실제 선택 전 다운로드 artifact별 checksum을 기록해야 합니다.

향후 self-hosted run이 full `RecommendationDecisionV2` 결과를 기록하면 아래처럼 평가할 수 있습니다.

```powershell
uv run --with-requirements requirements-contracts.txt python experiments/recommendation/evaluate_variants.py --responses path/to/results.json
```

결과 파일은 `{"results":[{"case_id":"case-01","variant":"A","repeat_index":0,"latency_ms":123.4,"expected_status":"completed","expected_product_id":"...","raw_response":"{...}"}, ...]}` shape입니다. 이미 parsing한 fixture라면 `raw_response` 대신 `decision` object를 넣을 수 있습니다. 각 case/variant를 최소 2회 반복해야 safe gate가 열립니다. Harness는 model을 호출하지 않고 raw JSON·schema 준수율, catalog ID, evidence grounding, expected-result 정확도, 반복 선택 안정성, 심리 단정 건수, latency와 실제 UTF-8 input bytes를 variant별로 요약합니다.

## Hard gate와 선택 규칙

후보나 variant는 모든 고정 fixture에서 다음 조건을 100% 통과해야 합니다.

- JSON schema/strict type 통과, catalog 밖 ID 0건, 금지 payload·심리 진단 0건
- 모든 decision evidence가 실제 같은-product window를 참조하고 matched tag가 DB controlled tag의 부분집합
- 충분한 신호 case는 정확히 Top 1 completed, 데이터 부족 case는 model을 호출하지 않고 no selection
- model revision, prompt, feature, catalog와 input variant version이 결과에 모두 기록됨
- target server에서 반복 실행 안정성, 최대 지연과 메모리 예산을 별도 측정

Hard gate를 모두 통과한 A/B/C가 fixture 선택·grounding에서 동률이면 C를 선택합니다. C는 timeline을 전달하지 않아 context와 frame-level 파생 신호 노출을 줄이기 때문입니다. A 또는 B가 C보다 명확하게 나은 경우에는 실패 case와 비용을 기록해 ADR에서 결정합니다.

## Model candidate registry

`model-candidates.v1.json`은 model 선택 결과가 아니라 server benchmark 대상 registry입니다.

- 1차 평가 후보: `Qwen/Qwen3.5-9B` revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, Apache-2.0
- 고자원 backup: `mistralai/Mistral-Small-3.1-24B-Instruct-2503` revision `68faf511d618ef198fef186659617cfd2eb8e33a`, Apache-2.0
- Gemma 3 12B는 gated Gemma license 때문에 기본 후보에서 제외

두 후보는 Korean/JSON instruction-following 관점의 후보이며 심리학·감정 분석 model로 표현하지 않습니다. 배포 runtime은 vLLM을 먼저 검토하고 target 환경에서 불가능할 때 Transformers fallback을 검증합니다. 최종 model과 quantization/runtime은 A/B/C 결과와 실제 server benchmark 뒤 ADR로 승인합니다.

## 파일

- `prompts/central-recommender.ko.v1.txt`: versioned Korean system prompt
- `model-candidates.v1.json`: exact model revision과 selection gate
- `evaluate_variants.py`: payload builder와 deterministic validator
- `results/model-benchmark-status.v1.json`: 실제 실행 여부를 과장하지 않는 상태 record
