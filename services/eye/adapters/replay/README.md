# Replay Eye Adapter

## 목적

승인된 파생 이벤트 fixture를 캡처 시각과 sequence 규칙에 따라 다시 내보내 통합·회귀 테스트를 재현한다.

## 입력과 출력

개인 식별 정보와 원본 미디어가 없는 `GazeSample` fixture와 replay clock 설정을 입력받아 같은 계약의 이벤트 stream을 출력한다.

## 경계

- 실제 고객의 얼굴 영상·이미지·base64 fixture를 읽지 않는다.
- fixture에 없는 값을 모델 추론으로 보충하지 않는다.
- pause·seek·replay는 `playback_epoch`을 보존하고, 순서 역전·drop은 scenario에 명시한다.

Python 구현은 `mcm_eye.ReplayEyeAdapter`다. fixture에는 캡처 context를 중복해서
저장하지 않고, 각 record의 `screen_x_norm`, `screen_y_norm`, `valid`, `confidence`,
`reason`만 둔다. Adapter가 호출된 `FrameContext`의 `session_id`, `frame_id`,
`video_time_ms`, `playback_epoch`을 그대로 `GazeSample`에 채운다. 같은 context 재시도는
같은 sample을 반환하고, 새 context는 다음 record를 소비한다.

```powershell
Set-Location services/eye
uv run pytest
```
