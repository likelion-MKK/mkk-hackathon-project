# Experiments

외부 모델 후보를 production 서비스와 분리해 조사·재현하는 영역이다. 후보마다 독립된 디렉터리와 환경을 사용하고 공용 lock 파일을 변경하지 않는다.

- `eye/`: 양유상 소유
- `face/`: 정은미 소유
- `recommendation/`: 양유상 모델·프롬프트 소유, 박형진 runtime·Contract 리뷰. Google Colab GPU self-hosted 후보와 별도 OpenAI Luna Max의 synthetic-only 검증 영역이며, 기존 gaze·expression 파생값을 심리학적 보조 신호로 제한해 평가한다. OpenAI lane은 live benchmark·후속 ADR 전 production 승인이 아니다.

실험 결과는 영역 README가 지정한 Git 제외 `artifacts/`와 정규화 보고서에 재현 절차와 함께 남기고, 선택 결정은 `docs/adr/`에 기록한다. 후보 코드나 weight를 production 경로로 복사하지 않는다.
