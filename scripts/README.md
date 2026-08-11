# Contract 검증

저장소 루트에서 독립된 검증 의존성을 설치한 뒤 실행합니다.

```powershell
python -m pip install -r requirements-contracts.txt
python scripts/validate_contracts.py
```

검증 항목:

- `contracts/**/*.schema.json`의 JSON Schema Draft 2020-12 문법
- `contracts/examples/*.json` 정상 fixture와 실행용 data fixture
- `contracts/examples/invalid/*.json`이 실제로 schema에서 거부되는지 확인
- `contracts/openapi.yaml` 문법, 필수 REST 경로와 WebSocket schema 참조
- manifest 시간 범위·중복 ID와 product catalog 참조
- reaction batch의 세션·영상 ID, event ID와 sequence 중복
- 완료된 추천 결과의 서로 다른 Top 2와 rank 1·2
- 추천·구매 결과의 product ID 참조
- event와 OpenAPI에 raw frame, image blob, bytes, base64 payload가 없는지 확인
- model weight·직렬화 모델 파일과 25 MiB 초과 일반 Git 파일 유입 차단

정상 example 이름은 기본적으로 동일한 schema 이름에 연결됩니다. 예를 들어 `gaze-sample.valid.json`은 `events/gaze-sample.schema.json`으로 연결됩니다.

## 선택적 명시 매핑

파일 이름이 다르면 `contracts/examples/schema-map.json`을 만들 수 있습니다.

```json
{
  "examples": {
    "gaze.v1.json": "../events/gaze-sample.schema.json",
    "../../data/products/catalog.example.json": "../product-catalog.schema.json"
  }
}
```

`mappings` 배열에서 `example`과 `schema` 필드를 사용하는 형식도 지원합니다. 매핑 대상이 없거나 중복·모호하면 검증이 실패합니다.

이 검증은 `frame_id`, `image_url` 같은 메타데이터 참조는 허용하지만 원본 프레임이나 이미지 payload를 담을 수 있는 key와 `data:image/...` URI는 거부합니다.
