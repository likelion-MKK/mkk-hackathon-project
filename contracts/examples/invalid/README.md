# 의도적으로 유효하지 않은 fixture

이 디렉터리의 JSON은 정상 예제가 아니며 일반 fixture 자동 검증 대상에서 제외합니다. Contract test에서는 각각이 대응 schema 검증에 **실패하는지** 확인하는 용도로만 사용합니다.

## `gaze-sample.invalid.json`

- 대응 schema: `contracts/events/gaze-sample.schema.json`
- 실패 이유: `screen_x_norm` 값이 `1.2`로, viewport 정규화 좌표 범위인 `0.0` 이상 `1.0` 이하를 벗어납니다.
- 이 예제에는 실제 고객 데이터나 원본 프레임이 없습니다.

원본 프레임, 이미지 바이트, blob 또는 base64 payload 필드는 Contract v1에 정의하지 않습니다. 각 object의 `additionalProperties: false` 규칙에 따라 그런 필드도 거부되어야 합니다.
