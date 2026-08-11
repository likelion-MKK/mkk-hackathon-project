# Face Candidate Experiments

## 소유자

정은미. 후보별 하위 디렉터리는 `<candidate-id>/`로 분리한다.

## 입력과 출력

고정된 비식별 fixture·하드웨어 조건과 정확한 URL/revision/license를 입력으로 사용한다. 출력은 label mapping, 검증 label이 있을 때의 macro-F1·class recall, score 안정성, p50/p95 지연·FPS, 자원 사용량, 실패 사례와 재현 명령이다.

## 금지사항

- 실제 고객 원본 영상, credential, model weight를 Git에 넣지 않는다.
- 라이선스·revision 고정·offline 실행 Hard Gate를 통과하지 못한 후보를 점수만으로 선택하지 않는다.
- 관찰 점수를 실제 감정·성격·구매 의도 검증으로 표현하지 않는다.
- 실험 의존성을 공용 서비스나 루트 lock 파일에 섞지 않는다.
