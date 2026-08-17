# Architecture Decision Records

승인된 모델·runtime·transport·기술 선택과 근거를 기록한다. 박형진이 Contract·Backend 결정 절차를 관리하고, 양유상은 중앙 추천 모델·시스템 프롬프트와 Eye ADR, 정은미는 Face ADR을 작성하며 영향받는 생산자·소비자가 리뷰한다.

각 ADR에는 상태, 결정일·소유자, 문제와 제약, 비교 후보, Hard Gate, 선택·fallback, 고정 revision·checksum·code/weight license, benchmark 환경·명령, 정량 결과·실패 사례, 포기한 장점, 알려진 한계와 재평가 조건을 포함한다.

후보 비교가 끝나기 전에 특정 모델을 `accepted`로 기록하거나, 미승인 제안을 확정 결정처럼 표현하지 않는다. 원본 프레임, credential, model weight는 첨부하지 않는다.

## 현재 ADR

| ADR | 상태 | 결정 범위 |
| --- | --- | --- |
| [`ADR-0001 원격 Eye·Face 추론 서버 전환`](0001-remote-vision-inference.md) | Proposed | Kiosk 카메라 frame의 일시적 WSS 전송, 서버 추론, 개인정보·장애·배포 Gate |
| [`ADR-0003 Face 모델·taxonomy·fallback 선정`](0003-face-model-taxonomy-fallback.md) | Proposed | MediaPipe 1차 선택안, 관찰 신호 taxonomy, fail-closed fallback과 D6 경계 |
| [`ADR-0004 EyeTrax 해커톤 MVP 선정`](0004-eyetrax-mvp-selection.md) | Accepted (해커톤 MVP 한정) | EyeTrax revision·Dense5 보정·개발 PC Gate와 재평가 조건 |
| [`ADR-0006 중앙 판단 추천 AI와 파생 evidence 수명`](0006-central-recommendation-ai.md) | Accepted (방향·경계) | derived-only self-hosted 중앙 판단, 룩북 종료 후 1회, MCM 가방 10개·Top 1, 세션 메모리 폐기와 비진단 설명 |
| [`ADR-0007 중앙 추천 모델 선정`](0007-central-recommendation-model-selection.md) | Proposed | Google Colab GPU 7개 후보의 provenance·자원·안전 benchmark와 블라인드 검토 뒤 model·runtime·variant 선정 |
| [`ADR-0008 OpenAI Luna 중앙 추천 모델 선택`](0008-openai-luna-central-recommendation.md) | Accepted — implementation baseline | Luna Max·max·variant C·prompt v4 선택, hosted provider migration과 통합 Gate |

ADR 번호 공백은 예약·이전 논의의 추적성을 위해 재사용하지 않는다. 생산자 ADR의 모델·taxonomy·보정 결정은 계속 유효하지만 추천 weight·파생 evidence 보유 방식이 충돌하면 ADR-0006이 우선한다.
