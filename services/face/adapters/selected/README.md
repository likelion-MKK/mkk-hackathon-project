# Selected Face Adapter

## 상태

외부 모델 선정 전의 비어 있는 production 연결 슬롯이다. 실제 모델 코드나 weight를 이 scaffold에 포함하지 않는다.

## 연결 조건

- Face 후보 최소 3개의 동일 조건 benchmark와 Hard Gate 결과가 있다.
- 선택·fallback ADR에 고정 revision, checksum, code/weight license, taxonomy mapping과 알려진 한계가 기록되어 있다.
- no-face·multi-face·unknown label을 포함한 `ExpressionSample` contract/replay test를 통과한다.

## 경계

모델 교체와 전처리·label 정규화는 이 슬롯 내부에서만 일어난다. weight는 Git에 넣지 않고, 승인된 재현 절차와 무결성 정보만 문서화한다.
