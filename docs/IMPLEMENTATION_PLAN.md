# 중앙 판단 추천 AI 구현 계획

- 상태: **Vertical slice implemented; production gates open**
- 작성일: 2026-08-18
- 기준선: `dev` commit `77ae806192db56ef2472439a0359380e7025fae2`
- 결정 기준: [`ADR-0006`](adr/0006-central-recommendation-ai.md)
- 구조 기준: [`OVERALL_DESIGN.md`](OVERALL_DESIGN.md)

이 문서는 승인된 목표의 구현 상태와 남은 production Gate를 함께 관리한다. 자동화
테스트를 통과한 vertical slice와 실제 환경에서 검증하지 않은 항목을 구분한다.

## 구현 현황 요약

| Workstream | 상태 | 확인된 결과 | 남은 Gate |
| --- | --- | --- | --- |
| W0 문서·결정 | 완료 | ADR-0008 Accepted, Luna hosted migration과 deployment baseline 기록 | 실제 secret·domain/TLS 운영 Gate |
| W1 v2 계약 | 완료 | 22 schema, v1/v2 example, AOI metadata, privacy negative fixture와 OpenAPI | 공동 리뷰·PR 승인 |
| W2 Vision·fusion·evidence | **3-A 완료 / 전체 미완료** | capture-time context, exact Eye·Face join, video 좌표, Backend 승인 AOI 경계, synthetic 계층·중첩 집계 | 실제 영상 AOI 검수(5번) 후 3-B 및 실기기 HTTPS/WSS E2E |
| W3 API·DB 운영화 | 로컬 구현 완료 | pooler/direct 분리, 0003 migration, 비덮어쓰기 10개 seed/readiness, atomic job lifecycle, restart/orphan/24h retention, backup/restore 절차 | live Supabase migration·backup/restore 및 개별 URL·자산·QR·tag 검수 |
| W4 모델·prompt | 구현 완료 | Luna Max, variant C, prompt v4, strict Responses adapter, no retry/timeout | 실제 key canary와 비용·rate-limit 운영 검증 |
| W5 Frontend 연결 | 구현 완료 | Kiosk v2 HTTP Top 1·template·cleanup, indefinite terminal polling, Vision token route, actual 33.5초 media identity | actual AOI·상품 자산·domain/TLS Browser E2E |
| W6 통합 검증 | 자동화 일부 완료 | Contract/API/Vision/Kiosk/Manager unit·replay·build, DB failure/readiness/lifecycle synthetic 검증 | Node 24, live Supabase, 실 Eye calibration, 로그/APM·browser 잔존 감사 |

## 1. 고정 범위

| 항목 | MVP 결정 |
| --- | --- |
| 중앙 입력 | 원본이 아닌 정형화된 시선·표정 파생 JSON |
| 실행 위치 | hosted `gpt-5.6-luna` Responses API; derived-only 경계 유지 |
| 호출 시점 | 룩북 종료 후 세션당 한 번 |
| 후보 | DB의 검수된 MCM 가방 정확히 10개 |
| 고객 결과 | Top 1 상품과 관찰 근거 설명 |
| frame 단위 파생값 | bounded session memory에서만 사용 후 폐기 |
| 영속 데이터 | 상품 카탈로그와 필요한 최소 최종 추천 |
| 구매·호감 피드백 | Deferred |
| 고객 유형·감정 표현 | 세션 한정 관찰 설명만 허용, 진단·성격 단정 금지 |

## 2. 기준선에서 확인된 호환성 차이

다음 표는 감사 기준점 `9d5881b`에서 확인했던 차이를 보존한다. 현재 해소 여부는 위
구현 현황과 각 영역 README를 우선하며, 구현되었다는 이유만으로 production Gate까지
통과한 것으로 보지 않는다.

| 경계 | 현재 상태 | 목표 | 필요한 결정 |
| --- | --- | --- | --- |
| 추천 결과 | Contract v1의 completed `items`는 정확히 2개이며 rank 상한도 2다. | 하나의 상품만 반환 | v1 호환 adapter 또는 새 major contract를 Contract PR에서 결정 |
| 중앙 입력 | `GazeSample`, `ProductAttentionEvent`, `ExpressionSample`, `ReactionBatch`가 분리되어 있고 중앙 세션 evidence 계약은 없다. | time-aligned bounded `RecommendationEvidence` | 새 schema, example, size·count limit, invalid 의미 승인 |
| 엔진 mode | 해소: v2 public `deployment_mode=self_hosted` 호환값은 유지하고 provider metadata를 별도 기록한다. | Luna runtime provider | ADR-0008 Accepted 기준의 실제 key canary·운영 readiness |
| 상품 데이터 | 예제 상품·lookbook 연결은 있으나 검수된 가방 10개 DB catalog는 보장하지 않는다. | exactly 10 active profiles | catalog schema, seed·migration, 검수 책임 승인 |
| 설명 | 기존 결과는 상품 ID 중심이다. | 근거 code·reference·비진단적 문구 | 설명 schema와 server-side grounding 결정 |
| 수명 | 생산자별 임시 상태는 있으나 중앙 evidence end-to-end 폐기 Gate가 없다. | final-only persistence | 성공·실패·취소·timeout cleanup test 추가 |

호환성 차이가 해소되기 전에는 새 UI나 runtime이 기존 v1 필드 의미를 조용히 바꾸지 않는다.

## 3. 작업 흐름과 소유자

### W0. 문서·결정 기준 고정 — 양유상

산출물:

- `OVERALL_DESIGN`, 이 계획과 ADR-0006의 정합성 유지
- 모델 평가표, system prompt spec과 안전 문구 기준
- 변경되는 결정마다 ADR·문서 지도 갱신

완료 Gate:

- 활성 문서에 운영 gaze-only 고정식, 복수 추천, frame timeline 영속화나 구매·호감 MVP 표현이 없다.
- 새 작업자가 문서 지도에서 현재 기준과 archive를 구분할 수 있다.

### W1. RecommendationEvidence Contract — 박형진 관리, 정은미·양유상 공동 리뷰

현재 v2 Contract에서 정의한 것:

- session·video·playback epoch와 capture time 기준
- frame별 시선 좌표·이동, 캡처 시점 video 좌표와 Backend 승인 AOI 기반 체류·재확인·왕복·지속 요약
- 표정 observable score, 변화율·지속 구간, quality·valid·reason
- Eye·Face 정렬 오차, coverage, drop·결측 요약과 evidence reference
- event count, payload bytes, 문자열·시간 범위 상한
- 직접 식별자·원본 frame·embedding·자유형 raw output 금지
- 성공·실패·취소·timeout의 메모리 폐기 의미

완료 Gate:

- 정상·일부 invalid·전체 부족·순서 역전·중복·상한 초과 example이 있다.
- producer와 consumer가 동일 fixture를 검증한다.
- `python scripts/validate_contracts.py`가 통과한다.

### W2. Vision 3-A·Eye/Face Producer와 Evidence Builder — 박형진·정은미, 양유상 Eye 검토

구현 순서:

1. Kiosk가 camera frame 생성 직전에 모든 capture/video context와 layout을 snapshot한다.
2. Gateway와 Kiosk가 Eye·Face 결과의 session/video/frame/sequence/capture/video-time/epoch 일치를 검증한다.
3. Kiosk는 캡처 layout으로 video 좌표까지만 만들고 product candidate는 보내지 않는다.
4. Backend만 canonical media identity와 승인 AOI를 검증해 상품·부위·tag로 매핑한다.
5. 같은 상품의 겹친 AOI는 모두 집계하고 다른 상품 중첩은 ambiguous로 fail-closed한다.
6. 동일 session·video·playback epoch 안에서 시선 이동·체류·재확인과 표정 변화·지속 feature를 결정적으로 계산한다.
7. invalid를 neutral·0점으로 채우지 않고 reason과 coverage를 유지한다.
8. finalize 뒤 immutable evidence를 한 번 만들고 모든 session buffer를 정리한다.

완료 Gate:

- 3-A: 지연 응답에도 캡처 시점 `video_time_ms`가 유지되고, letterbox·영상 밖·불일치 context가 상품을 만들지 않는다.
- 3-A: actual AOI가 승인 전이면 Backend가 `aoi_metadata_unapproved`를 반환한다.
- synthetic replay fixture에서 같은 입력이 같은 evidence와 version을 만든다.
- pause·seek·replay, frame drop, 순서 역전, no-face, low-confidence와 일부 worker 실패를 검증한다.
- payload가 DB·로그·APM·browser storage에 남지 않는다.

Vision 전체 완료 Gate는 별도다.

- 5번 데이터 작업에서 actual 33.5초 영상의 시간 구간, polygon, 상품, component, visual tag, parent 관계를 담당자가 검수하고 `approved` revision으로 고정한다.
- 3-B에서 actual valid gaze → 캡처 시점 video time/point → 같은 상품의 전체·세부 AOI → 정확한 product/component/tag → 집계 evidence를 재검증한다.
- 3-B 전에는 “상품을 아는 Vision E2E” 또는 Vision 전체 완료로 표시하지 않는다.

### W3. MCM 가방 10개 Catalog — 박형진 구현, 양유상 내용, 조윤혜 표시 검토

산출물:

- stable product ID, 공식명, 이미지·상세·QR URL
- 형태·크기·소재·색상·사용 장면의 사실 기반 태그
- 설명에 쓸 검수 문구와 금지 주장
- schema/content version, 활성 상태와 검수 provenance
- 정확히 10개 active profile을 보장하는 seed·migration·readiness check
- Supabase session pooler runtime과 direct 우선·IPv4 session pooler fallback migration/backup
  credential 분리
- `pending→running→terminal` atomic transition, cancel-late 차단과 restart/orphan cleanup
- terminal 최소 metadata 24시간 retention 및 `/healthz`·`/readyz` 분리

완료 Gate:

- 10개가 아니면 central AI readiness가 실패한다.
- 기존 승인 catalog를 seed가 덮어쓰지 않고 ID/revision/tag 불일치를 자동 보정하지 않는다.
- 재시작·취소·30분 orphan·24시간 retention 뒤 원본 evidence를 복구하거나 DB에 남기지 않는다.
- 모든 룩북 AOI product ID와 catalog ID가 검증된다.
- 모델 출력이 아닌 DB가 고객 표시 사실의 원천이다.

### W4. 중앙 판단 모델·프롬프트 — 양유상 결정, 박형진 runtime

모델 평가 항목:

- hosted provider의 strict output, latency·rate-limit·secret 경계
- exact revision, code·weight license, checksum과 공급망 안전성
- strict JSON 준수율, 후보 밖 ID 비율, 한국어 근거 품질
- 심리·감정·성격 과잉 추론과 근거 없는 상품 사실 생성 비율
- 일부 invalid·insufficient evidence·prompt injection성 문자열에 대한 fail-closed 동작
- 동일 replay에 대한 결정 안정성과 fallback/rollback 가능성

시스템 프롬프트는 최소 다음을 version으로 고정한다.

- 입력은 관찰 가능한 파생 신호이며 실제 감정·성격·구매 의도가 아님
- 후보는 전달된 10개 ID로 제한
- 상품 하나만 선택하고 evidence reference와 allowlist reason code를 반환
- evidence가 부족하면 `insufficient_data`
- 제품 사실은 제공된 catalog 이외에 생성 금지
- 자유형 진단·유형 단정·민감 속성 추론 금지

완료 Gate:

- 선택 모델·revision·prompt version과 benchmark 결과를 후속 ADR 또는 ADR-0006 개정으로 승인한다.
- output validator가 schema, exactly-one ID, allowlist, reason reference와 금지 문구를 검사한다.
- timeout·invalid output을 고객용 임의 추천으로 대체하지 않는다.

### W5. API·Kiosk·Manager 연결 — 조윤혜, 박형진 Backend

산출물:

- S03 종료 시 Backend finalize를 한 번 요청하는 idempotent 흐름
- pending·completed·insufficient_data·failed 상태 UI
- Top 1 카드, DB 기반 상품 정보·QR, 세션 관찰 근거와 한계 문구
- 고객 버튼으로만 Manager request 생성, REST polling 소비

완료 Gate:

- frame·장면마다 중앙 AI가 호출되지 않는다.
- 페이지 refresh·retry가 중복 추천이나 중복 매니저 요청을 만들지 않는다.
- 자동 매니저 호출이나 별도 실시간 push를 필수 경로로 만들지 않는다.
- “@@ 유형”이나 실제 감정 확정 문구가 렌더링되지 않는다.

### W6. 통합·개인정보 검증 — 전원

필수 시나리오:

- 정상 룩북 → 정확히 한 AI 호출 → 후보 내 Top 1 → evidence 폐기
- 일부 Eye/Face invalid → reason 보존 → 충분하면 근거 제한, 부족하면 분석 불가
- no-face·network 단절·model timeout·invalid JSON·후보 밖 ID
- pause·seek·replay·중복 finalize·세션 취소·만료
- catalog 9개·11개·비활성·룩북 ID 불일치
- 로그·DB·cache·queue·APM·browser storage와 crash/error 경로의 원본·evidence 비잔존

완료 Gate:

- Contract, unit, replay, integration, Frontend lint/test/build가 각 영역 README 기준으로 통과한다.
- 한 세션에서 central model invocation count가 1임을 검증한다.
- 종료 뒤 session evidence 조회·재사용이 불가능함을 검증한다.
- 고객 문구 red-team 결과와 알려진 한계를 기록한다.

## 4. PR 순서

```text
P0 Decision docs
  → P1 RecommendationEvidence + Result contract
  → P2 Producers + Evidence Builder
  → P3 Product Catalog + migration
  → P4 Model evaluation + prompt decision
  → P5 Luna runtime + strict validator
  → P6 API/Kiosk/Manager consumers
  → P7 Wiring + privacy/E2E gate
```

각 PR은 `dev`에서 시작하고 `dev`를 base로 한다. P1의 공유 계약이 합의되기 전에 P2–P6가 서로 다른 임시 JSON을 공식 형식으로 만들지 않는다. Fake·Replay로 consumer 작업을 준비할 수 있지만 production 의미는 승인된 contract fixture를 따른다.

## 5. 연구 baseline의 위치

기존 gaze score, dwell·revisit 계산과 Face 보조 weight 실험은 replay·비교 baseline으로 보존한다. 중앙 판단 AI의 production 정책이나 고객 성격·감정 판단으로 승격하지 않는다. 새 모델은 기존 baseline과 동일 fixture에서 정확성뿐 아니라 출력 준수, 근거성, 안전성, 지연과 실패 동작을 함께 비교한다.

## 6. Deferred 진입 조건

구매·호감 feedback은 다음이 별도 승인될 때만 새 단계로 시작한다.

1. 무엇을 호감·구매로 볼지와 누가 입력하는지 정의
2. 명시적 동의, 목적, 보유 기간, 삭제·철회 경로
3. 최소 표본·편향·성능 평가와 이전 모델 비교
4. feature·weight·dataset·model version 및 rollback
5. 운영 DB·접근 권한·감사와 개인정보 검토

그 전에는 UI·API·DB에 future-proofing을 이유로 고객 feedback을 수집하거나 숨겨 저장하지 않는다.

## 7. 남은 결정

- 실제 OpenAI key canary와 provider rate-limit/cost 운영 기준
- A/B/C 실제 반복 benchmark에 따른 input variant 승인
- catalog 10개 상품의 개별 공식 URL, 이미지·QR 라이선스와 tag·설명 최종 검수
- actual `mcm-lookbook-v2` 전체 AOI·부위·색상·소재 tag 검수와 Vision 3-B
- 최소 최종 추천 metadata의 보유 기간·삭제 정책
- live Supabase 재시작·pending orphan cleanup·backup/restore와 운영 readiness
- 승인 Vision producer, 실제 Browser E2E, Node.js 24.19.0 재검증
- insufficient-data 화면 문구와 재시도 UX의 사용자 테스트

이 항목은 담당자가 근거를 수집해 Contract·ADR·migration 또는 UI PR에서 결정한다. 임시 기본값을 공식 결정처럼 문서화하지 않는다.
