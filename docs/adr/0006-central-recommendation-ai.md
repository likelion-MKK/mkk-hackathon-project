# ADR-0006 중앙 판단 추천 AI와 파생 evidence 수명

- 상태: **Accepted (방향·경계)**
- 결정일: 2026-08-16
- 결정 소유자: 양유상(문서·모델·시스템 프롬프트)
- 구현 소유자: 박형진(Contract·Backend·DB·runtime)
- 공동 리뷰: 정은미(Face·표정 evidence), 조윤혜(Kiosk·Manager), 양유상(Eye evidence)
- 기준선: `dev` commit `9d5881b`
- 관련 ADR: [`ADR-0001`](0001-remote-vision-inference.md), [`ADR-0003`](0003-face-model-taxonomy-fallback.md), [`ADR-0004`](0004-eyetrax-mvp-selection.md)

이 ADR은 추천 의사결정 구조와 파생 evidence 수명을 승인한다. 구체적인 중앙 모델·revision·시스템 프롬프트의 선택까지 완료했다는 뜻은 아니다. 해당 값은 benchmark와 안전 평가 후 이 ADR의 후속 결정으로 고정한다.

## 1. Context

기존 설계는 Eye/AOI 집계와 고정 가중치 연구 baseline을 중심으로 추천하고 Face 신호는 낮은 보조 비중으로 제한했다. 문서마다 복수 상품 추천, 파생 event의 DB 보관, 구매 전환 수집과 Manager 자동 알림이 섞여 현재 제품 방향을 일관되게 설명하지 못했다.

새 방향은 Eye·Face에서 얻을 수 있는 관찰 정보를 먼저 정형화하고, 룩북 전체 맥락과 검수된 상품 profile을 중앙 판단 AI가 함께 비교하도록 한다. 다만 웹캠 원본을 추천 모델에 전달하거나 표정으로 실제 감정·성격을 진단해서는 안 된다.

## 2. Decision

### 2.1 중앙 판단 경계

1. Eye·Face 생산자는 frame을 처리해 정규화된 파생 sample·event를 만든다.
2. Evidence Builder는 같은 session·video·playback epoch의 capture time과 `video_time_ms`를 기준으로 시선 좌표·이동·체류·재확인·표정 관찰값·변화율·지속성·품질·무효 사유를 결합한다.
3. 중앙 AI에는 bounded `RecommendationEvidence` JSON만 전달한다. 원본 frame·영상·image bytes·base64·embedding·원본 경로는 입력에 포함하지 않는다.
4. 중앙 AI는 팀이 통제하는 self-hosted runtime에서 실행한다. 외부 hosted AI API를 production 판단 경로로 사용하지 않는다.
5. 룩북이 종료되고 evidence가 finalize된 뒤 세션당 한 번만 호출한다.
6. 후보군은 DB의 활성·검수된 **MCM 가방 정확히 10개**다.
7. 정상 결과는 후보 안의 **Top 1** 상품, allowlist reason code, evidence reference와 비진단적 설명이다.
8. schema 위반, 후보 밖 상품, 근거 없는 설명 또는 신호 부족은 fail-closed한다.

### 2.2 데이터 수명

- 원본 frame은 ADR-0001이 허용하는 Vision 추론 메모리에서만 처리하고 해당 frame 성공·실패·timeout 뒤 해제한다.
- frame 단위 파생 sample·event와 결합 evidence는 bounded session memory에서만 유지한다.
- 추천 성공·실패·취소·만료와 제한된 retry 종료 뒤 evidence와 request state를 폐기한다.
- 파일, PostgreSQL, object storage, cache, queue, 로그, APM, browser storage, artifact와 backup에 frame 단위 timeline을 저장하지 않는다.
- DB에는 상품 10개 profile과 필요한 최소 최종 추천만 저장한다. 최소 metadata와 보유 기간은 별도 정책으로 확정한다.

파생 수치도 세션·시간 등 다른 정보와 쉽게 결합되어 개인을 알아볼 수 있다면
[개인정보보호법 제2조](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1030669293)의
개인정보 범위로 취급한다. MVP의 세션 메모리 한정, 목적 달성 뒤 즉시 폐기와
필드 allowlist는 최소수집·파기 원칙인
[제16조](https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1029335669)와
[제21조](https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900078981)를
기본 설계 기준으로 삼는다. 이는 개별 배포의 법률 검토·동의 문구·보유 정책 승인을
대체하지 않는다.

### 2.3 고객 설명

추천 설명은 이 세션의 관찰 사실과 DB의 검수된 상품 사실에만 근거한다.

- 허용: “이번 룩북에서 A 가방 구간을 비교적 오래 보고 다시 확인한 반응이 관찰되어 추천합니다.”
- 금지: 실제 감정·성격·심리 유형·민감 속성·구매 의도의 확정 또는 진단

“고객님은 @@ 유형”을 기본 결과로 사용하지 않는다. 이후 유형 요약을 검토하더라도 세션 한정 관찰 label, 비진단 고지, 사용자 테스트와 별도 승인이 필요하다.

### 2.4 피드백 학습

구매·호감 feedback 수집, 개인화와 가중치·모델 재학습은 Deferred다. MVP는 해당 데이터를 입력·저장·학습하지 않는다. 향후 도입에는 별도의 동의·목적·보유·삭제·편향 평가·version·rollback 결정이 필요하다.

### 2.5 Manager

Manager event는 S04에서 고객이 명시적으로 요청 버튼을 눌렀을 때만 생성한다. Manager는 REST polling으로 소비한다. 시선·표정 변화, 룩북 시작 또는 추천 완료에 따른 자동 호출과 별도 실시간 push는 MVP 결정이 아니다.

## 3. RecommendationEvidence 계약 원칙

상세 field 이름은 Contract PR에서 정하되 다음 의미를 보존한다.

| 범주 | 포함 의미 |
| --- | --- |
| capture | sequence/frame reference, monotonic capture time, video time, playback epoch |
| gaze | normalized coordinates, validity·confidence·reason, coordinate movement, AOI/product relation, dwell·revisit·oscillation·duration summary |
| face | allowlist observable scores, validity·quality·reason, change rate·duration·notable interval |
| alignment | Eye·Face matching tolerance/result, coverage, drop·missing summary |
| provenance | schema, producer, model, taxonomy, manifest와 feature version |

직접 식별자, 원본 binary, embedding, 자유형 raw model output, 진단 label과 구매·호감 feedback은 금지한다. event 수, payload bytes, 문자열, 시간창과 retry를 상한으로 제한한다. invalid는 `(0, 0)`, neutral 또는 무관심으로 바꾸지 않는다.

## 4. 중앙 모델·프롬프트 Gate

양유상은 Hugging Face 또는 다른 오픈소스 후보 중 self-hosted 가능한 모델을 비교한다. “감정 분석”이나 “심리학”이라는 model-card 설명은 선택 근거의 일부일 뿐이며 다음을 실제 project fixture에서 검증한다.

- immutable revision, code·weight license, checksum과 안전한 load 방식
- 목표 hardware의 warmup·latency·memory·안정성
- strict JSON, 후보 10개 allowlist와 exactly-one 결과 준수율
- evidence reference의 정확성, catalog 밖 사실 생성 비율과 한국어 설명 품질
- 감정·성격·민감 속성 과잉 추론, prompt injection과 일부 invalid 입력
- insufficient-data, timeout, rollback과 deterministic replay 비교

시스템 프롬프트는 입력의 비진단적 의미, 금지 추론, 후보 제한, 근거 요구, 부족 시 실패와 strict output schema를 version으로 고정한다. 모델 출력의 제품 사실은 고객에게 직접 표시하지 않고 DB profile로 다시 grounding한다.

## 5. Contract·DB 영향

이 ADR 승인 뒤 현재 작업 브랜치에는 v1을 보존하는 v2 Contract, 10개 catalog profile과
PostgreSQL migration·seed adapter가 구현되었다. 아직 공유 PR 승인이나 production 배포를
뜻하지 않으며 live PostgreSQL 검증과 보유 정책 승인이 남아 있다.

- `RecommendationEvidence` schema·example·size limit·cleanup 의미
- Top 1 결과 schema 또는 현재 Contract v1과의 명시적 호환 방식
- model·prompt·evidence·catalog version과 status/error 의미
- MCM 가방 10개 catalog schema, seed·migration과 readiness invariant
- 최소 최종 추천 metadata와 보유·삭제 정책

현재 Contract v1의 completed result가 두 item을 요구하는 점은 [`IMPLEMENTATION_PLAN`](../IMPLEMENTATION_PLAN.md)에 호환성 차이로 기록한다. v1 field의 이름·수·의미를 문서만으로 바꾸지 않는다.

## 6. Supersedes와 보존 범위

이 ADR이 대체하는 추천 계층의 이전 방향:

- gaze-only 또는 고정 수식·weight를 production 최종 판단으로 쓰는 방향
- Face를 항상 낮은 보조 weight로만 결합한다는 추천 정책
- frame 단위 파생 reaction timeline을 DB에 영구 저장하는 방향
- 구매·호감·전환 feedback을 MVP 학습 입력으로 수집하는 방향
- 운영 고객 결과를 복수 상품으로 고정하는 방향

이 ADR이 대체하지 않는 생산자·인프라 결정:

- ADR-0001의 원본 frame 전송 승인 Gate, WSS·Gateway·비저장 경계
- ADR-0003의 Face 관찰 taxonomy, invalid·fallback과 producer lifecycle
- ADR-0004의 EyeTrax 해커톤 MVP 선택, 보정·좌표 생산자와 재평가 조건
- 기존 Eye·Face benchmark와 replay evidence

생산자 ADR에 적힌 추천 weight·retention 문구만 이 ADR이 우선하며 모델·taxonomy·adapter 근거는 계속 보존한다.

## 7. Alternatives

### 규칙 기반 gaze score만 운영

재현성과 설명은 쉽지만 풍부한 시간·표정 맥락과 상품 profile을 함께 판단하기 어렵다. 연구·replay baseline으로 보존하고 production 최종 정책으로 채택하지 않는다.

### frame마다 멀티모달 AI 호출

지연·비용·개인정보 노출 면적과 불안정성이 크고 원본 전송 경계를 넓힌다. 선택하지 않는다.

### 외부 hosted 추천 API

파생 신호라도 제3자 전송 승인·보유·학습 사용 조건이 추가된다. MVP는 self-hosted로 고정한다.

### frame timeline 영구 저장 후 batch 분석

재현에는 유리하지만 현재 목적에 비해 개인정보·보유·접근 위험이 크다. synthetic/replay fixture로 재현하고 고객 timeline은 저장하지 않는다.

### 구매·호감 즉시 수집

초기 데이터 부족을 보완할 가능성은 있으나 의미·동의·편향·학습 Gate가 준비되지 않았다. Deferred로 둔다.

## 8. Consequences

### 긍정적 결과

- Eye·Face 팀이 생산자 의미를 유지하면서 중앙 판단 정책과 독립적으로 개발할 수 있다.
- 전체 세션의 시계열 맥락과 상품 태그를 한 판단 경계에서 비교할 수 있다.
- 원본 frame과 고객 timeline 영속화를 피하면서 근거 있는 추천을 제공한다.
- 특정 모델을 바꾸더라도 evidence·catalog·strict output 계약으로 소비자를 보호한다.

### 비용·위험

- v2 evidence·result, catalog migration과 UI vertical slice를 유지·검증해야 한다.
- 생성 모델의 비결정성·환각·과잉 심리 추론을 validator와 eval로 통제해야 한다.
- frame timeline을 저장하지 않으므로 운영 사건 재현은 version·aggregate metric과 승인된 replay fixture에 의존한다.
- 구체적인 모델·input variant·weight checksum·결과 보유 기간은 아직 결정되지 않았다.

## 9. Rollout Gate와 rollback

production 연결 전 다음을 모두 만족한다.

- [x] RecommendationEvidence와 Top 1 결과 Contract·example·자동화 tests 구현
- [x] MCM 가방 exactly 10 catalog와 합성 replay AOI ID 무결성 검증
- [ ] 선택 모델 revision·license·checksum·benchmark와 prompt version 승인
- [x] 후보 밖 ID, 복수 결과, 근거 없는 설명과 심리 단정 fail-closed 자동화 검증
- [x] 정상·invalid·insufficient·timeout·취소·중복 finalize 합성 replay 통과
- [x] test-only stub에서 세션당 중앙 모델 호출 수 1 검증
- [x] 앱 구조·테스트에서 종료 뒤 transient frame·derived evidence 삭제와 timeline DB table 부재 확인
- [ ] S04 Top 1·한계 문구·명시적 Manager 요청 E2E 통과

체크된 항목도 현재 branch의 fixture·test 범위다. live PostgreSQL, 실제 model server,
reverse proxy·APM와 실제 Browser를 사용한 비잔존 검증은 별도 production Gate다.

회귀 시 다른 미승인 모델, gaze score 또는 임의 상품으로 조용히 대체하지 않는다. 중앙 추천 runtime을 unready로 만들고 `failed` 또는 `insufficient_data` UI로 종료한다. 이미 승인된 이전 central model revision이 생긴 뒤에만 동일 contract·catalog·prompt 호환성과 rollback owner를 확인해 되돌린다.

## 10. 재평가 조건

- 후보 상품 수나 결과 개수를 바꿀 때
- 외부 hosted AI나 원본 frame 입력을 검토할 때
- frame 단위 evidence의 영속 저장이 필요해질 때
- 구매·호감 feedback 학습을 시작할 때
- 모델이 설명 안전성·latency·strict output Gate를 충족하지 못할 때
- 실제 사용자 평가에서 추천 근거가 오해·차별·과잉 진단을 유발할 때
