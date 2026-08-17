# ADR-0008 OpenAI Luna 중앙 추천 모델 선택

- 상태: **Proposed — selected pending integration reviews**
- 작성일: 2026-08-17
- 선택일: 2026-08-17
- 결정 소유자: 양유상(모델·프롬프트·품질 기준)
- 구현·Contract 검토: 박형진(대기)
- 소비자 문구 검토: 조윤혜(대기)
- 선행 결정: [`ADR-0006`](0006-central-recommendation-ai.md), [`ADR-0007`](0007-central-recommendation-model-selection.md)

## 결정

중앙 추천 production candidate로 다음 조합을 선택한다.

- model: `gpt-5.6-luna`
- reasoning: `effort=max`, `context=current_turn`
- input: variant C 전체 파생 JSON, 검수된 상품 정확히 10개
- prompt: `central-recommender-ko-v4`, SHA-256 `bc1186d1e3f1e908e8a865ae8f89c35f7e6c3172ccd010018101141d5a350149`
- API: Responses API, `store=false`, tool·web·conversation 없음
- retry: 0
- client timeout: 없음
- application output-token 상한: 없음
- 출력 보호: strict JSON Schema, JSON text 16KiB, catalog·evidence·tag validator
- 입력 보호: 6,000 tokens 초과 시 호출 전 차단
- latency: 측정·기록만 하며 완료 Gate로 사용하지 않음

현재 상태는 `selected_pending_adr_and_integration`이다. 이 ADR의 박형진·조윤혜 리뷰와 hosted provider 경계 승인이 끝나기 전 production 연결 완료로 간주하지 않는다.

## 근거

`diagnostic-full-v4-no-timeout.json`에서 합성 callable 9개를 3회씩 총 27회 실행했다.

- 27/27 expected Top 1·strict output·catalog membership 통과
- 동일 입력 3/3과 catalog 순서 변경 안정성 통과
- 시선·얼굴 action 필수 reason/evidence grounding 통과
- return 후보 수치 제거에 근거가 함께 변경됨
- 데이터 부족·catalog 오류 3건은 외부 호출 0회
- 심리·감정·성격·구매 의도 단정, 근거 없는 상품 사실, prompt injection 이행 0건
- 기록용 p95 73,581.757ms, 최대 111,855.914ms

사용자는 긴 추론시간을 허용하고 latency를 완료 기준에서 제외했다. 따라서 위 지연 수치는 선택을 막지 않는다.

v5 입력 축소안은 완료 호출 지연이 여전히 길었고 27회 중 16회가 provider HTTP 429에서 fail-closed 되어 선택하지 않는다. 완전히 검증된 v4 조합을 선택한다.

## 안전·실패 경계

- 원본 frame·영상·image bytes·base64·embedding·원본 경로를 보내지 않는다.
- 입력은 allowlist된 Eye·Face 파생값과 검수된 10개 상품 profile로 제한한다.
- 모델 출력이 schema를 위반하거나 catalog 밖 ID, 복수 상품, 근거 없는 ref·tag를 포함하면 추천 없이 실패한다.
- incomplete, refusal, 429, 5xx와 연결 오류는 재시도하지 않고 fail-closed 한다.
- 응답시간 제한은 없지만 사용자 취소와 프로세스 종료 경로에서는 세션 evidence를 폐기해야 한다.
- 모델 생성 상품 설명을 그대로 표시하지 않고 DB의 검수된 문구로 grounding한다.

## ADR-0006과의 관계

ADR-0006의 derived-only, 세션당 1회, 정확히 10개 중 Top 1, 최소 저장, 비진단 설명과 fail-closed 원칙은 유지한다. 다만 self-hosted runtime 원칙을 hosted OpenAI API로 바꾸는 제안이므로 이 ADR이 Accepted 되기 전에는 기존 self-hosted 경계가 공식적으로 우선한다.

## Contract·DB·통합 영향

이번 선택 변경은 Contract·DB·migration·운영 API를 수정하지 않는다. 박형진의 후속 통합에서 다음을 검증한다.

- 세션 종료 후 정확히 1회 Responses API 호출
- 실제 DB의 검수된 MCM 상품 정확히 10개 전달
- `OPENAI_API_KEY` secret 관리와 로그·APM 비노출
- 16KiB·catalog·evidence·tag strict validator
- 429·5xx·refusal·incomplete fail-closed와 evidence cleanup
- 사용자 취소 가능 상태와 장시간 대기 UI
- 동시 세션의 rate-limit 관측 및 운영 readiness

## 승인 전 남은 Gate

- [x] Luna Max variant C 합성 품질 27/27
- [x] replay·순서 변경·ablation·preflight·red-team Gate
- [x] latency를 기록 전용으로 변경하는 사용자 결정
- [ ] 양유상 prompt·한국어 문구 최종 서명
- [ ] 조윤혜 장시간 대기·취소 UX와 고객 설명 검토
- [ ] 박형진 hosted provider·Contract·secret·rate-limit 검토
- [ ] 실제 DB 10개 catalog와 통합 replay 검증

기계 판독 상태는 [`openai-luna-max-status.v5.json`](../../experiments/recommendation/results/openai-luna-max-status.v5.json)에 기록한다.
