# End-to-End Tests

## 소유와 입력

조윤혜가 사용자 흐름을, 박형진이 API·DB·Manager 경계를 주도하고 전원이 Gate에서
확인한다. Fake/Replay Adapter와 AI stub은 계약·실패 흐름을 재현할 때만 사용하며 실제
추천 성공으로 표시하지 않는다.

## 검증 결과

S01→S04, 동의·취소·timeout, 카메라 거부, 데이터 부족, 네트워크 단절, v2 Top 1·QR,
고객 명시 요청에 의한 Manager REST polling과 clean session reset을 검증한다. v1 Top 2와
conversion은 호환성 회귀로만 남긴다.

## 금지사항

Mock 추천을 실제 추천으로 표시하지 않으며, E2E 성공을 실제 모델 정확도나 알고리즘 품질의 증거로 사용하지 않는다.

## D7 Replay E2E

`test_d7_replay_e2e.py`는 실제 camera·고객 영상·외부 network 없이 기존 v1 Gate C 경로를
검증하는 호환성 replay다.

```text
runtime synthetic frame 또는 Face 파생 replay fixture
  → D7 in-process Gateway harness
  → Replay Eye + FaceWorker
  → ExpressionSample + ProductAttentionEvent
  → ReactionBatch → FastAPI MemoryStore
  → MockRecommendationEngine → deterministic P001/P002
```

실행 명령:

```powershell
Set-Location apps/api
uv sync --locked
uv run pytest -c pyproject.toml --rootdir . ../../tests/contract ../../tests/integration ../../tests/e2e
```

`apps/vision_gateway`의 handshake·envelope·drop/close 타입은 D7 in-process harness
내부 의미이며 production Vision Stream v1 계약이 아니다. Eye 서버 transport가 아직
없으므로 P001/P002 AOI를 가리키는 파생 gaze replay port를 사용한다. Face 결과는 이 v1
test에서는 추천 입력에 직접 사용하지 않고, 추천 결과는 항상 `engine_mode=mock`으로
검증한다. 운영 acceptance는 별도의 v2 replay에서 Eye·Face 결합 관찰값, self-hosted AI
경계, 정확히 한 상품과 transient buffer 폐기를 확인해야 한다.
