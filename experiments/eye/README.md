# Eye Candidate Experiments

## 소유자

양유상. 후보별 하위 디렉터리는 `<candidate-id>/`로 분리한다.

## 입력과 출력

고정된 비식별 fixture·하드웨어 조건·보정 절차와 정확한 URL/revision/license를 입력으로 사용한다. 출력은 AOI hit·target 오차·valid 비율·jitter, p50/p95 지연·FPS, 자원 사용량, 실패 사례와 재현 명령이다.

## 금지사항

- 실제 고객 원본 영상, credential, model weight를 Git에 넣지 않는다.
- 라이선스·revision 고정·offline 실행·화면 좌표 변환 Hard Gate를 통과하지 못한 후보를 점수만으로 선택하지 않는다.
- 정답 label이 없는 시연 영상 결과를 정확도라고 부르지 않는다.
- 실험 의존성을 공용 서비스나 루트 lock 파일에 섞지 않는다.

## 현재 후보 실험

- [`eyetrax/`](eyetrax/README.md): 단일 사용자·개발 PC에서 실행하는 EyeTrax 라이브 보정·AOI 정확도 benchmark
