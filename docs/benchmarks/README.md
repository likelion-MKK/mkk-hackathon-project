# Benchmark Reports

Eye는 양유상, Face는 정은미가 같은 하드웨어·fixture·입력 순서·보정 절차에서 cold/warm 반복 결과를 기록한다. 박형진은 D5·D9 Gate의 재현성과 개인정보 경계를 확인한다.

보고서에는 실행 날짜, OS·CPU/GPU/RAM, 후보 URL과 고정 revision, code/weight license, 설치·실행 명령, fixture version, 반복 수, p50/p95·FPS·자원 사용량, 영역별 품질 지표, 실패 조건, raw metric artifact 위치와 요약을 포함한다.

실제 고객 원본 미디어·credential·weight를 저장하지 않는다. 후보마다 다른 조건을 사용한 결과를 한 순위표에서 직접 비교하지 않으며, 정답 label이 없는 결과는 `안정성 관찰`로 표시한다.

Face D4의 고정 synthetic workload, 후보별 결과와 임시 label 비교는 [`face/README.md`](face/README.md)에서 확인한다.

Vision 서버의 사업자·region·instance는 [`VISION_SERVER_SELECTION_PLAN.md`](VISION_SERVER_SELECTION_PLAN.md)의 순서에 따라 workload와 모델을 먼저 고정하고, CPU → fractional GPU → full GPU의 최소 사양 탐색, 현장 network·동시 세션, 같은 날짜의 총비용 비교를 통과한 뒤 결정한다. 최종 선택은 benchmark 보고서와 후속 ADR-0002에 기록하며 이 디렉터리의 가격 스냅샷만으로 배포하지 않는다.
