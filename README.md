# MCM AI Lookbook Kiosk

> 룩북에서 관찰된 시선·표정 파생 신호를 중앙 판단 AI가 해석해 MCM 가방 한 개와 근거를 제안하는 매장형 키오스크

## 현재 MVP 방향

고객은 회원가입이나 설문 없이 약 60초의 룩북을 본다. Eye·Face 생산자는 웹캠 frame을 처리해 시선 좌표, 상품 구간, 체류·재방문, 표정 관찰값과 변화·지속 정보를 만든다. 원본 frame은 추천 AI로 보내지 않는다.

룩북이 끝나면 Backend가 세션 메모리에 있는 파생 신호를 한 번의 `RecommendationEvidence`로 정리한다. self-hosted 중앙 판단 AI는 이 JSON과 DB에 등록된 **MCM 가방 정확히 10개**의 태그·분석을 비교해 **Top 1** 상품과 근거를 반환한다.

```text
웹캠 frame(추론 중 메모리만)
  → Eye·Face 파생 신호
  → 시간·상품 기준 RecommendationEvidence JSON(세션 메모리)
  + DB의 MCM 가방 10개 프로필
  → 룩북 종료 후 self-hosted 중앙 판단 AI 1회 호출
  → Top 1 상품 ID + 관찰 근거 설명
  → 최종 추천만 저장, frame 단위 파생값은 폐기
```

## 사용자 흐름

| 화면 | 사용자 경험 |
| --- | --- |
| **S01. Screensaver** | 대기 화면을 터치해 서비스를 시작한다. |
| **S02. Main Menu** | AI 추천을 선택하고 카메라·분석 안내와 동의를 확인한다. |
| **S03. AI Lookbook** | 약 60초 룩북을 보며 시선·표정의 관찰 가능한 신호를 수집한다. |
| **S04. Analysis Report** | 추천 가방 한 개, 세션에서 관찰된 근거와 상품 QR을 확인한다. 필요할 때 고객이 직접 매니저 호출을 누른다. |

매니저 요청은 고객의 명시적 버튼 입력으로만 생성하며 Manager 화면은 REST polling으로 확인한다. 분석 시작이나 추천 완료만으로 자동 호출하지 않는다.

## AI 설명 원칙

시선·표정 신호는 실제 감정, 성격이나 구매 의도를 확정하지 않는다. 고객 문구는 이 세션에서 관찰된 행동과 상품 장면만 설명한다.

benchmark에서는 기존 파생값을 상대적 시각적 주의·관찰 가능한 action 변화라는 심리학적 보조 신호로 제한해 평가할 수 있지만, 이는 supporting factor이며 새 심리 필드나 진단값을 만들지 않는다.

- 사용 가능: “룩북에서 A 가방이 나온 구간을 비교적 오래 보고 다시 확인한 반응이 관찰되어 추천합니다.”
- 사용 금지: “고객님은 충동형입니다”, “행복한 감정이므로 이 상품을 좋아합니다.”

유형명을 꼭 표시해야 한다면 진단·성격 분류가 아니라 “이번 룩북 세션의 관찰 요약”임을 함께 밝히고, 근거가 부족하면 유형이나 추천을 만들지 않는다.

## 데이터 수명과 개인정보

| 데이터 | 처리 원칙 |
| --- | --- |
| 웹캠 원본 frame·영상·image bytes·embedding | 동의된 Vision 추론 수명 동안 메모리에서만 처리하며 파일·DB·로그·cache·queue·추천 AI 입력에 남기지 않는다. 원격 Vision 전송은 [`ADR-0001`](docs/adr/0001-remote-vision-inference.md)이 승인되기 전 실제 고객에게 적용하지 않는다. |
| frame 단위 시선·표정 파생값과 결합 evidence | 세션 메모리에 제한해 룩북 종료 후 한 번의 추천에 사용하고 성공·실패·취소 뒤 폐기한다. |
| 상품 카탈로그 | 검수된 MCM 가방 10개의 ID, 태그와 설명을 DB에 저장한다. |
| 최종 추천 | 상품 ID, 비진단적 설명, 알고리즘·모델·프롬프트 버전과 최소 운영 metadata만 정책에 따라 저장한다. |
| 구매·호감 피드백 | MVP 입력이나 학습에 사용하지 않는다. 동의·보유 기간·편향 평가를 별도 승인하는 후속 범위다. |

## 팀 역할

| 팀원 | 현재 책임 |
| --- | --- |
| 양유상 | 공식 문서 최신화, 중앙 판단 모델 후보·revision·license 평가, 시스템 프롬프트와 출력 기준 작성, Eye 신호 의미 검토 |
| 조윤혜 | Kiosk·Manager와 Backend 계약 차이 점검, S01–S04 연결과 필요한 Frontend 수정 |
| 박형진 | 파생 evidence 계약·집계·API·DB 경계, 시선 정보 정형화, 중앙 AI runtime 연결 |
| 정은미 | 표정 관찰 신호·변화·지속 정보 정형화, Face 생산자 의미와 evidence 결합 검토 |

공유 계약은 생산자와 소비자가 함께 리뷰하며 구현 순서는 `Contract·example → Producer → Consumer → Wiring`을 따른다.

## 현재 상태와 구현 경계

문서 기준선은 `dev`의 `a6eb3d78f47ce38da9d0b2be9b0794479986e280`이고, 이 작업 브랜치에는 중앙 추천 v2 vertical
slice가 구현되어 있다.

- v1을 깨뜨리지 않는 frame observation·evidence·Top 1·Manager v2 계약과 privacy
  negative fixture
- 정확히 10개 상품 profile, PostgreSQL migration·기동 시 seed/readiness adapter
- bounded session buffer, frame fusion, 비동기 1회 호출, strict output 검증과
  성공·실패·취소·TTL cleanup
- Kiosk의 real HTTP v2 흐름과 code+DB tag 기반 고객 문구, Manager REST polling
- versioned Korean prompt, Google Colab GPU 7개 후보 registry, A/B/C·12개 합성 case의 self-hosted benchmark CLI

다만 production 준비가 끝났다는 뜻은 아니다. 실제 self-hosted 모델은 아직 선택·실행하지
않았고, live PostgreSQL·실제 Browser E2E·승인된 Vision producer도 검증 전이다. 공식
listing에서 상품명만 확인했으므로 개별 상품 URL·이미지·QR은 `null+reason`이며 팀 검수와
자산 승인이 필요하다. 현재 Frontend 검증은 Node.js 22.19.0에서 수행되어 요구 버전
24.19.0 재검증도 남아 있다.

구현 순서와 호환성 차이는 [`IMPLEMENTATION_PLAN`](docs/IMPLEMENTATION_PLAN.md)을 기준으로 한다.

## Frontend 로컬 실행

Node.js `24.19.0`과 npm을 사용한다.

```powershell
npm install
npm run dev:kiosk
npm run dev:manager
```

```powershell
npm run lint
npm run test
npm run build
```

Kiosk는 기본적으로 `http://localhost:5173`, Manager는 `http://localhost:5174`에서 실행한다. Backend 주소는 각 앱의 `.env.example`을 따른다.

## 공식 문서

- [문서 지도와 읽기 순서](docs/DOCUMENT_MAP.md)
- [전체 설계](docs/OVERALL_DESIGN.md)
- [구현 계획](docs/IMPLEMENTATION_PLAN.md)
- [ADR-0006 중앙 판단 추천 AI](docs/adr/0006-central-recommendation-ai.md)
- [ADR-0007 중앙 추천 모델 선정 초안](docs/adr/0007-central-recommendation-model-selection.md)
- [ADR-0008 OpenAI Luna 중앙 추천 모델 선택](docs/adr/0008-openai-luna-central-recommendation.md)
- [중앙 추천 self-hosted benchmark](experiments/recommendation/README.md)
- [2026-08-16 dev 문서·브랜치 감사](docs/audits/2026-08-16-dev-document-branch-audit.md)
- [AI Agent 작업 규칙](AGENTS.md)
- [개발 및 PR 운영 규칙](CONTRIBUTING.md)
- [Contract v1·v2](contracts/README.md)

Eye·Face benchmark와 SJF 자료는 공식 결정의 근거·협업 참고자료로 보존하며, 현재 제품 방향은 위 공식 문서를 우선한다.
