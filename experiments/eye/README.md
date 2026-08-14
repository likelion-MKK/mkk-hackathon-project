# Eye Candidate Experiments

## 소유자

양유상. 후보별 하위 디렉터리는 `<candidate-id>/`로 분리한다.

공식 조사 순서, 검색 종료 조건, Hard Gate와 100점 추천 기준은 [`D2 Eye Tracker 전수 조사·추천 계획`](../../docs/benchmarks/EYE_CANDIDATE_RESEARCH_PLAN.md)을 따른다.

## D2 결과 구조

```text
inventory/search-manifest.json  # 검색어·기준 시각·API page·날짜 분할
inventory/candidates.jsonl      # 발견한 전체 후보와 deduplication·상태
evidence/reviews.jsonl          # 사용자 후기 URL·환경·직접 사용·관찰
<candidate-id>/                 # 후보별 격리 환경·README·lock·smoke
```

후보 상태는 `pass-commercial`, `pass-demo-only`, `deferred`, `fail` 중 하나다. Hard Gate와 online·offline Smoke를 통과한 후보만 D2-4 점수표에 들어가며, 상위 최대 3개만 D4 동일 조건 benchmark로 진입한다.

## 입력과 출력

고정된 비식별 fixture·하드웨어 조건·보정 절차와 정확한 URL/revision/license를 입력으로 사용한다. D2 Smoke 출력은 설치·모델 load·출력 shape·offline 재실행·기본 자원 관찰이며 정확도 비교가 아니다. D4 이후에는 같은 조건에서 AOI hit·target 오차·valid 비율·jitter, p50/p95 지연·FPS, 자원 사용량, 실패 사례와 재현 명령을 기록한다.

## 금지사항

- 실제 고객 원본 영상, credential, model weight를 Git에 넣지 않는다.
- 라이선스·revision 고정·offline 실행·화면 좌표 변환 Hard Gate를 통과하지 못한 후보를 점수만으로 선택하지 않는다.
- GitHub stars·Hugging Face downloads·단일 추천 글을 정확도나 사용자 만족도로 바꾸지 않는다.
- 후보마다 다른 입력·하드웨어·반복 조건의 Smoke 관찰값을 한 성능 순위표에서 비교하지 않는다.
- 정답 label이 없는 시연 영상 결과를 정확도라고 부르지 않는다.
- 실험 의존성을 공용 서비스나 루트 lock 파일에 섞지 않는다.
