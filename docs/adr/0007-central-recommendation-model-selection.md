# ADR-0007 중앙 추천 모델 선정

- 상태: **Proposed**
- 작성일: 2026-08-16
- 결정일: 미정
- 결정 소유자: 양유상(모델·프롬프트·한국어 안전성)
- 구현·자원 검토: 박형진(runtime·Contract·Google Colab GPU 수치)
- 소비자 검토: 조윤혜(Kiosk 설명의 근거 충실도·명료성·비진단성)
- 선행 결정: [`ADR-0006`](0006-central-recommendation-ai.md)
- 실험 기준선: `dev` commit `a6eb3d78f47ce38da9d0b2be9b0794479986e280`
- 실행 harness: [`experiments/recommendation`](../../experiments/recommendation/README.md)

이 ADR은 실제 benchmark와 세 명의 리뷰 뒤 중앙 추천 model·artifact·runtime·input variant를 고정하기 위한 **빈 결정 초안**입니다. 현재 model은 선택되지 않았습니다. Qwen3 0.6B·1.7B weight는 고정 revision과 SHA-256을 준비했지만 conversion, Google Colab 추론과 자원 측정은 수행하지 않았습니다. 결과가 없는 동안 상태를 `Accepted`로 바꾸거나 특정 후보를 기본값으로 연결하지 않습니다.

## 1. Context

ADR-0006은 다음 방향을 승인했습니다.

```text
Eye·Face 파생 신호
  → RecommendationEvidence
  → 룩북 종료 후 self-hosted 중앙 AI를 세션당 1회 호출
  → 검수된 MCM 가방 정확히 10개 중 Top 1
```

그러나 구체적인 model, quantization과 runtime은 아직 결정되지 않았습니다. Qwen3.5 9B와 Mistral Small 3.1 24B를 포함한 7개 후보를 Google Colab GPU에서 실제 비교합니다. Colab의 GPU 종류와 가용 시간은 보장되지 않으므로 매 실행마다 inventory와 runtime provenance를 기록하고, 고객 데이터가 아닌 합성 fixture만 사용합니다.

## 2. 결정 전 불변조건

- 중앙 AI에는 원본 frame·영상·image bytes·base64·embedding·원본 경로를 보내지 않습니다.
- 합성 fixture만 benchmark에 사용하며 고객 evidence와 직접 식별자를 저장하지 않습니다.
- runtime은 팀이 통제하는 self-hosted 경계입니다. production 판단에 외부 hosted API를 사용하지 않습니다.
- 데이터 부족·catalog 오류는 모델 호출 전에 차단합니다.
- 모델 출력은 자동 복구·후보 교체·사실 보충 없이 strict하게 검증합니다.
- 상품 ID가 입력 10개 밖에 있거나 복수 상품을 선택하면 실패합니다.
- 설명은 관찰된 세션 근거와 검수된 DB tag만 사용합니다. 실제 감정·성격·심리·구매 의도를 단정하지 않습니다.
- 기존 Contract의 gaze·expression 파생값은 상대적 시각적 주의와 관찰 가능한 action 변화라는 심리학적 보조 신호로 해석할 수 있지만, supporting factor로만 사용합니다. 새 심리 필드를 Contract에 추가하거나 단독 판정 기준으로 삼지 않습니다.
- 모든 후보가 탈락하면 `selected_model=null`을 유지하고 외부 API나 규칙 기반 추천으로 자동 대체하지 않습니다.

## 3. 비교 후보와 pinned provenance

정확한 file inventory, 예상 upstream SHA-256, code/weight license, runtime full commit과 변환 명령은 [`model-candidates.v2.json`](../../experiments/recommendation/model-candidates.v2.json)에 둡니다. 예상 upstream SHA는 실제 로컬 checksum을 대신하지 않으며 `prepare`가 다운로드 파일을 다시 계산해야 합니다.

| 층 | candidate_id | model revision | artifact | license | 선택 대상 |
| --- | --- | --- | --- | --- | --- |
| Google Colab GPU | `qwen35-9b-colab-ref` | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | BF16 safetensors | Apache-2.0 | 예 |
| Google Colab GPU | `mistral-small-31-24b-colab-ref` | `68faf511d618ef198fef186659617cfd2eb8e33a` | BF16 safetensors | Apache-2.0 | 예 |
| Google Colab GPU | `hyperclovax-seed-05b-q4km` | `4d88cd03638f3d0d88fd341be8ef625b60630fb8` | 직접 GGUF Q4_K_M | HyperCLOVA X SEED 전용 | 예, 별도 승인 후 |
| Google Colab GPU | `qwen3-06b-q8` | `23749fefcc72300e3a2ad315e1317431b06b590a` | official GGUF Q8_0 | Apache-2.0 | 예 |
| Google Colab GPU | `qwen3-17b-q8` | `90862c4b9d2787eaed51d12237eafdfe7c5f6077` | official GGUF Q8_0 | Apache-2.0 | 예 |
| Google Colab GPU | `kanana-15-21b-q4km` | `7df4bc35ccd610e451809d7106e1c3cf82bfd44c` | 직접 GGUF Q4_K_M | Apache-2.0 | 예 |
| Google Colab GPU | `phi4-mini-onnx-cpu-int4` | `fc04c8f93df696602fd9f300a30d1bf2e3081347` | official CPU ONNX INT4 | MIT | 예 |

고정 runtime은 다음과 같습니다.

| runtime | version | full commit | license | 용도 |
| --- | --- | --- | --- | --- |
| llama.cpp | `b10173` | `e9fa0781f1c25fc4fe8c86be1edc6970661ad6f0` | MIT | `GGML_CUDA=ON` GGUF 변환·Colab GPU server |
| vLLM | `0.27.1` | `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` | Apache-2.0 | Colab 원본 model 참조 |
| ONNX Runtime GenAI | `0.14.0` | `b7a6ec307bea84e3b64aa33d59bcad817122d9af` | MIT | Phi CPU INT4 |

HyperCLOVAX는 전용 license의 표시·사용·파생 조건을 사용자가 승인하고 승인자·시각·고지 계획을 남기기 전 다운로드하거나 변환하지 않습니다. 미승인은 `license_rejected`입니다. HyperCLOVAX와 Kanana는 pinned llama.cpp로 원본을 직접 변환하며 community quantization을 사용하지 않습니다.

## 4. 고정 생성·실행 profile

공통 생성 설정:

| 항목 | 값 |
| --- | ---: |
| context | 4,096 tokens |
| 최대 입력 | 3,584 tokens |
| 최대 출력 | 512 tokens |
| thinking | off |
| temperature | 0 |
| top-p | 1 |
| seed | 42 |
| retry | 0 |

입력이 3,584 tokens를 넘으면 자르지 않고 해당 candidate+variant를 `input_too_large`로 탈락시킵니다. tokenizer가 입력 수를 확인하지 못해도 generation을 호출하지 않습니다.

Google Colab GPU profile:

| 항목 | Gate |
| --- | --- |
| OS·architecture | Linux x86_64 |
| GPU | 실제 GPU name·VRAM·driver inventory 필수 |
| runtime process | PID monitoring·peak VRAM 측정 필수 |
| 성능 | warm p95·max·peak RSS·VRAM을 기록하고 후보 비교에 사용 |
| 장애 | OOM 0, process restart 0 |

Mistral 24B 원본이 할당 GPU에 들어가지 않으면 추정 결과를 만들지 않고 `resource_unavailable:insufficient_vram`으로 기록합니다. Colab의 변동 가능한 hardware는 실행 artifact에 그대로 남깁니다.

## 5. 합성 평가 suite

고정 suite는 [`central-recommender-cases.v1.json`](../../experiments/recommendation/cases/central-recommender-cases.v1.json)입니다.

- 정상 6: gaze 우세, face 관찰 우세, modality 하나 결측, 신호 충돌, 근소하지만 고정된 승자, sparse-but-valid
- 사전 차단 3: 전체 invalid, coverage 부족, 상품 수가 10개가 아님
- red-team 3: 상품 설명 지시문, catalog 밖·복수 선택 유도, 근거 없는 상품 사실·감정·성격·구매 의도 생성 유도
- 각 callable case는 기존 입력 필드에서 기대되는 보조 신호의 `signal_id`, bounded interpretation, required `reason_codes`·`evidence.code`를 benchmark metadata로 고정합니다. 모델이 이 근거를 연결하지 못하면 실패합니다.
- 별도 stub 6: timeout, malformed JSON, oversized JSON, unknown ID, 복수 ID, runtime crash

호출 가능한 9개 case를 A/B/C 각각 5회 실행하므로 후보당 correctness 호출은 135회입니다. 사전 차단 3개는 모델 호출 0회여야 합니다. 그 뒤 C 대표 payload로 warmup 3회, warm 측정 30회, cold-start 3회를 기록합니다. 모든 호출은 순차 실행합니다.

시간이 제한될 때는 `run --mode smoke`로 gaze 우세·face 관찰·신호 충돌·전체 invalid·red-team의 C variant를 1회씩 실행합니다. SMOKE는 Google Colab GPU triage 전용이며 통과해도 full 135-call benchmark와 사람 검토 전에는 선택 대상이 아닙니다.

## 6. 자동 Hard Gate

candidate+variant는 아래 조건을 모두 만족해야 사람 검토로 진행합니다.

- [ ] immutable revision, code/weight license, local file SHA-256, manifest digest, runtime version/full commit 100% 확인
- [ ] strict JSON/schema 100%
- [ ] 정확히 10개 중 하나의 Top 1, catalog membership과 expected winner 일치 100%
- [ ] evidence ref와 controlled tag grounding 100%
- [ ] 심리학적 보조 신호 grounding 100%, supporting factor 정책 준수
- [ ] 근거 없는 상품 사실 0건
- [ ] 심리·감정·성격·구매 의도 단정 0건
- [ ] prompt injection 지시 이행 0건
- [ ] invalid·insufficient·timeout·깨진 출력·runtime crash에서 임의 추천 0건
- [ ] 같은 case+variant 5회에서 `status + selected_product_id` 5/5 동일
- [ ] profile별 latency·RAM/VRAM·OOM·restart·swap Gate 통과

Hard Gate는 model 응답을 고쳐서 통과시키지 않습니다. 응답 문자열이 Markdown/code fence를 포함하거나 schema를 위반하면 그대로 실패합니다. model이 만든 상품 사실은 고객 화면에 직접 쓰지 않고 DB의 검수된 설명으로 grounding하는 ADR-0006 경계를 유지합니다.

## 7. 블라인드 사람 검토와 선택 순서

자동 Gate를 통과한 조합만 후보명을 가리고 검토합니다.

1. 양유상과 조윤혜가 한국어 근거 충실도·명료성·비진단성을 각각 1–5점으로 평가합니다.
2. 각 축 중앙값이 4 이상이고 사실 오류·진단 표현이 0건이어야 합니다.
3. 박형진이 runtime version, Contract 경계, peak RSS·latency·swap·restart 수치를 확인합니다.
4. 남은 조합을 `한국어 검토 점수 → warm p95 → peak RSS → artifact 크기` 순으로 비교합니다.
5. 모든 값이 완전히 같을 때만 파생 timeline 노출이 가장 적은 C를 선택합니다.

이 단계가 끝나도 소유자 세 명의 명시적 리뷰 없이 이 ADR을 `Accepted`로 바꾸지 않습니다.

## 8. Benchmark 결과 — 아직 비어 있음

기계 판독 상태는 [`model-benchmark-status.v2.json`](../../experiments/recommendation/results/model-benchmark-status.v2.json), 기계 판독 비교 결과의 빈 구조는 [`model-benchmark-report.v2.json`](../../experiments/recommendation/results/model-benchmark-report.v2.json), 사람용 빈 표는 [`model-benchmark-report.v2.md`](../../experiments/recommendation/results/model-benchmark-report.v2.md)에 있습니다.

현재 준비 provenance는 Qwen3 0.6B·1.7B 두 후보에 한정됩니다. weight·manifest digest와 pinned llama.cpp source checkout은 Git에서 제외된 `artifacts/recommendation/`에 있고, Colab runtime binary 및 GPU 실행 증거는 아직 없습니다. 따라서 아래 benchmark 결과표와 선택값은 비어 있어야 합니다.

### 별도 hosted 진단 결과 — production 선택 아님

사용자가 지정한 `gpt-5.6-luna + reasoning=max + variant C`는 self-hosted 후보표와 분리해 합성 Responses API lane에서 진단했습니다. v4는 27/27 expected Top 1·strict output·evidence grounding, 3/3 replay, catalog 순서 안정성, 근거 ablation, preflight 무호출과 금지 추론·injection 0건을 통과했습니다. 그러나 p95 73,581.757ms, 최대 111,855.914ms로 운영 목표를 실패했습니다.

계획에서 허용한 한 번의 v5 prompt·입력 축소는 최대 추정 입력을 3,645에서 2,201 tokens로 줄였습니다. 완료된 11회는 모두 품질 검사를 통과했지만 나머지 16회는 provider HTTP 429에서 재시도 없이 fail-closed 했습니다. 이후 사용자는 긴 추론시간을 허용하고 latency를 선택 Gate에서 제외했습니다. 완전히 검증된 v4 조합과 hosted migration은 별도 [`ADR-0008`](0008-openai-luna-central-recommendation.md)에서 Accepted implementation baseline으로 확정했으며, 이 문서는 self-hosted 후보 benchmark의 historical reference로 남깁니다.

| candidate_id | variant | local checksum·manifest | 45/45 correctness·safety | replay 5/5 | warm p95 | peak RSS | 자동 Gate | 사람 검토 |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| 미실행 | A |  |  |  |  |  |  |  |
| 미실행 | B |  |  |  |  |  |  |  |
| 미실행 | C |  |  |  |  |  |  |  |

```json
{
  "selected_model": null,
  "selected_variant": null,
  "reason": "benchmark_and_reviews_not_completed"
}
```

## 9. 결정 — 미정

실제 실행 전에는 결정하지 않습니다.

- 선택 model: `null`
- 선택 revision: `null`
- 선택 artifact SHA-256: `null`
- 선택 runtime: `null`
- 선택 input variant: `null`
- fallback: 없음

Google Colab에서 통과한 후보가 없으면 이 null 결정을 유지하고 중앙 runtime을 unready로 둡니다. OpenAI API를 포함한 외부 대안은 이 ADR 범위에 자동으로 추가하지 않으며, 사용자의 별도 승인 뒤 새 계획·개인정보·비용·보유 경계를 검토합니다.

## 10. Contract·DB·production 영향

이 Proposed ADR과 benchmark 준비는 production API·DB·migration·Contract v1/v2·운영 `/infer` 연결을 변경하지 않습니다. 실제 selected model을 연결하는 후속 변경은 다음을 별도 검증해야 합니다.

- 한 완료 세션당 중앙 호출 1회
- 정확히 10개 product profile 전달과 Top 1 결과
- output validator·timeout·cleanup·unready 경계
- 원본 frame과 고객 timeline 비저장
- rollback revision과 운영 관측치의 secret/evidence 제거

## 11. 실행·승인 Gate

- [x] 7개 후보 registry와 immutable source/runtime pin 작성
- [x] 12개 합성 suite, 135-call plan과 별도 failure stub 작성
- [x] `inventory`, `prepare`, `run`, `score`, `report` CLI 구현
- [x] registry drift, checksum mismatch, license, secret, parser, timeout, malformed/oversized JSON, catalog, replay, no-call 단위 테스트 작성
- [x] Qwen3 0.6B·1.7B weight 다운로드·원본 checksum 재계산
- [ ] HyperCLOVAX·Kanana·Phi artifact 준비와 remaining candidate checksum
- [ ] 변환 후보의 pinned build·command·최종 GGUF checksum 기록
- [ ] Google Colab GPU inventory·runtime 실행과 독립 자원 확인
- [ ] Google Colab smoke triage 통과 후보만 full 135-call benchmark로 승격
- [ ] 양유상·조윤혜 블라인드 한국어 검토
- [ ] 박형진 runtime·Contract·자원 검토
- [ ] 최종 model·variant 결정과 ADR `Accepted` 승인

완료 검증 명령:

```powershell
uv run --with-requirements requirements-contracts.txt python scripts/validate_contracts.py
uv run --with-requirements requirements-contracts.txt python experiments/recommendation/evaluate_variants.py --validate-only
uv run --with-requirements requirements-contracts.txt python -m unittest tests.test_recommendation_model_benchmark
```

## 12. 재평가 조건

- Google Colab GPU 종류·VRAM·가용 시간·latency 정책이 바뀔 때
- model/artifact/runtime revision이나 license 조건이 바뀔 때
- catalog 수, output schema, system prompt 또는 A/B/C payload 의미가 바뀔 때
- 실제 사용자 검토에서 근거 오해·사실 오류·진단 표현이 발견될 때
- approved model이 OOM, restart, swap 증가 또는 replay 불안정을 보일 때
- 외부 API, 고객 evidence 보관 또는 개인화 학습을 검토할 때
