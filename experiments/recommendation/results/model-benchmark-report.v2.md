# 중앙 추천 모델 benchmark 비교 보고서

- 상태: **Not run**
- 실행 provider/profile: **Google Colab / `colab-gpu`**
- 입력: synthetic fixture only
- weight: Qwen3 0.6B·1.7B 다운로드 및 SHA-256/manifest 검증 완료; 변환 없음
- Colab 실행: 수행하지 않음
- 외부 provider: 사용하지 않음
- 최종 선택: 없음 (`selected_model=null`)
- 심리학적 보조 신호: 기존 gaze·expression 필드에서 상대적 주의·관찰 가능한 action 변화를 supporting factor로 평가; Contract 추가 필드 없음
- SMOKE: Google Colab GPU triage 전용이며 full benchmark·선정 대상 아님

## 준비 단계 provenance

| 후보 | weight SHA-256 | manifest SHA-256 | runtime |
| --- | --- | --- | --- |
| `qwen3-06b-q8` | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` | `64217f47ee2f7d5d2d619ddcbeebd7142b9b2a6d85857551a54abf99b4bd148d` | pinned source만 준비, binary 없음 |
| `qwen3-17b-q8` | `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a` | `ddc070e86f5732cfb3e729329b289c8cc7799939898f55644c3b5472642bab93` | pinned source만 준비, binary 없음 |

weight와 raw preparation JSON은 Git에서 제외된 `artifacts/recommendation/`에만 있습니다. 현재 호스트는 Windows이며 Colab GPU runtime·inference와 resource measurement는 수행하지 않았습니다.

## 자동 Hard Gate 결과

| 실행 층 | 익명 후보 | Variant | provenance | JSON·Top 1·grounding | safety·fail-closed | replay 5/5 | 자원 Gate | 결과 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Google Colab GPU | 미실행 | A |  |  |  |  | N/A |  |
| Google Colab GPU | 미실행 | B |  |  |  |  | N/A |  |
| Google Colab GPU | 미실행 | C |  |  |  |  | N/A |  |

빈 칸은 실패가 아니라 아직 측정하지 않았다는 뜻입니다. 실제 `score` 출력으로 대체하기 전 수치를 채우지 않습니다.

## 보조 신호 Gate

callable case마다 사전에 정한 `reason_codes`와 `evidence.code`가 입력의 관찰 신호와 연결되는지 확인합니다. 모델이 심리·감정·성격·구매 의도를 단정하거나 보조 신호를 단독 판정처럼 사용하면 실패 처리합니다.

## 자원 결과

| 후보·variant | artifact bytes | peak RSS | warm p95 | warm max | cold-start 3회 | OOM | restart | persistent swap growth |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 미실행 |  |  |  |  |  |  |  |  |

## 블라인드 사람 검토

자동 Hard Gate를 통과한 조합만 후보명을 가리고 검토합니다.

| 익명 조합 | 검토자 | 한국어 근거 충실도 1–5 | 명료성 1–5 | 비진단성 1–5 | 사실 오류 | 진단 표현 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 검토 전 | 양유상 |  |  |  |  |  |
| 검토 전 | 조윤혜 |  |  |  |  |  |
| 검토 전 | 박형진(runtime·Contract·자원) | N/A | N/A | N/A |  |  |

## 선택 결과

```json
{
  "selected_model": null,
  "selected_variant": null,
  "reason": "benchmark_and_reviews_not_completed"
}
```

모든 Google Colab 조합이 탈락하면 이 null 상태를 유지합니다. 외부 API나 규칙 기반 추천으로 자동 대체하지 않습니다.
