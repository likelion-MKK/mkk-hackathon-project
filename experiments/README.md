# Experiments

외부 모델 후보를 production 서비스와 분리해 조사·재현하는 영역이다. 후보마다 독립된 디렉터리와 환경을 사용하고 공용 lock 파일을 변경하지 않는다.

- `eye/`: 양유상 소유
- `face/`: 정은미 소유

실험 결과는 `docs/benchmarks/`에 재현 절차와 함께 요약하고, 선택 결정은 `docs/adr/`에 남긴다. 후보 코드나 weight를 production 경로로 복사하지 않는다.
