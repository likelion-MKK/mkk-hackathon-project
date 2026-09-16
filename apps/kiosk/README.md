# Kiosk App

## 책임과 현재 경계

조윤혜가 S01–S04 화면, 영상·웹캠 orchestration과 Backend 연결을 담당한다. 공유 Vision·추천 계약은 박형진·양유상·정은미와 함께 리뷰한다.

기본 실행은 실제 FastAPI에 연결하는 중앙 추천 v2 transport다. live Vision은 브라우저 `getUserMedia` → signed token → Vision Gateway → private Eye worker 경계를 구현했으며, 현재 표정 관찰은 비활성화되어 `expression=null`, `expression_reason=not_observed`로만 전송된다. [`ADR-0001`](../../docs/adr/0001-remote-vision-inference.md)이 Proposed이고 domain/TLS가 미확정인 동안 public customer traffic은 열지 않는다. 원본 frame·image bytes·base64·embedding·원본 경로는 REST payload, 브라우저 저장소, 로그나 추천 AI 입력에 포함하지 않는다.

## Real HTTP v2 흐름

```text
S01 대기 → S02 가방 룩북 선택·동의 → 보정 → S03 33.5초 실제 룩북
  → 4Hz 분석 frame의 시선·표정 파생값을 frame_id로 결합
  → POST /api/v2/sessions/{id}/observations
  → POST /api/v2/sessions/{id}/complete
  → GET /api/v2/sessions/{id}/recommendation REST polling
  → completed인 경우에만 DB의 MCM 가방 10개 중 Top 1 표시
  → 고객이 버튼을 누른 경우에만 v2 manager-product-request 전송
```

real mode는 actual `mcm-lookbook-v2` manifest와 v2 계약을 사용한다. Kiosk는 camera frame 생성 직전에 `session_id`, `video_id`, `frame_id`, `sequence`, `captured_at_mono_ms`, `video_time_ms`, `playback_epoch`, video layout을 한 번 snapshot하고 응답 시점의 `currentTime`을 다시 읽지 않는다. 시선 신호는 그 snapshot에만 결합하고 원래 sequence와 frame-drop gap을 보존한다. 표정은 현재 관찰하지 않는다. seek·replay·source 교체는 이후 frame보다 먼저 epoch를 증가시킨다.

Kiosk는 캡처 시점 layout으로 viewport gaze를 실제 video content rectangle의 `video_x_norm`, `video_y_norm`으로 변환한다. letterbox·pillarbox·영상 밖·무효 gaze에는 상품을 만들지 않으며 production observation의 `candidates`는 항상 빈 배열이다. 승인 AOI를 적용해 상품·부위·태그를 정하는 책임은 Backend에만 있다.

Kiosk의 분석 cadence는 250ms 간격인 4Hz다. 실제 33.5초 영상은 약 134 observation을 만든다. 60초·240 observation 경로는 `mcm-central-ai-replay-v2` 합성 fixture 전용이며 actual 설정과 섞지 않는다. frame drop이나 modality 차이로 batch 상한을 넘으면 모든 observation을 보존한 채 다음 batch로 분할한다.

## 고객 설명과 상품 자산

S04는 `completed` 결과의 단일 `selected_product_id`만 표시한다. `insufficient_data`와 `failed`는 추천 성공처럼 대체하지 않고 명시적인 오류 화면으로 보낸다. 고객의 명시적 매니저 요청은 `session_id + recommendation_id` 기반의 안정적인 `request_id`를 재사용해 응답 유실 후 재시도도 중복 이벤트가 되지 않게 한다.

고객 문구는 AI 자유 문장을 그대로 표시하지 않는다. 서버가 검증한 `exploration_tendency_code`, `reason_codes`와 DB의 `controlled_tags`를 Frontend allowlist 템플릿에 매핑한다. 감정·성격·심리 유형이나 구매 의도를 단정하지 않는다.

검수 전 상품은 정보가 연결되지 않았다는 안내를 표시한다. 검수 완료 상품은 공식 개별 상품 링크와 상품 정보를 표시하며, 사진 로딩 실패가 상품명과 링크를 숨기지는 않는다. 이미지 경로와 실제 파일은 별개이며 로컬에서는 승인 파일을 `public/assets/products/<product_id>/`에 배치해야 한다.

## 데이터 수명과 취소

- 분석 frame, `GazeSample`, `ExpressionSample`, 결합 observation과 derived timeline은 현재 세션 메모리에만 둔다.
- Backend가 snapshot을 만든 뒤 성공·실패·취소·만료되면 transient buffer를 폐기한다.
- Kiosk도 append/complete 뒤 로컬 배열을 비우며, 취소·timeout·append/complete 실패 시 `DELETE /api/v2/sessions/{id}`를 best-effort로 호출한다.
- 구매·호감 수집과 학습 반영은 MVP 범위가 아니다.

## v1 Mock fixture

`VITE_USE_MOCK_API=true`일 때만 `MockApiClient`와 Contract v1 Top 2 fixture를 사용한다. 이 경로는 과거 화면·호환성 테스트용이며 production 추천 동작을 설명하지 않는다. 화면에도 Mock fixture임을 명시한다.

## 설정과 실행

`.env.example`의 기본값은 다음 의미를 가진다.

- `VITE_API_BASE_URL`: 실제 FastAPI 주소
- `VITE_API_PROXY_TARGET`: 필요한 경우 Vite 개발 proxy 대상
- `VITE_USE_MOCK_API=false`: 기본 real HTTP v2
- `VITE_VISION_MODE=replay`: synthetic/in-process development producer
- `VITE_VISION_MODE=live`: browser `getUserMedia` → Vision Gateway WSS → Eye;
  현재 표정은 `not_observed`로 고정하고, production은 backend token mode를 사용하며 Eye unavailable이면 fail-closed한다.
- `VITE_LOOKBOOK_ID=mcm-lookbook-v2`: 33.5초 actual canonical 가방 룩북
- `VITE_LOOKBOOK_VIDEO_URL`: 로컬에서는 `/media/mcm-lookbook-v2.mp4`로 staging한
  canonical 영상, 배포에서는 Nginx `/media/` static path

중앙 Luna 추천 polling에는 기본 20초 timeout이 없다. Kiosk는 `completed`,
`failed`, `insufficient_data`까지 기다리며 사용자가 취소하면 AbortSignal로 job을
취소한다. 자동 orphan cleanup은 API에서 30분 후 수행한다.
- `VITE_KIOSK_DEBUG_AOI`: 개발용 AOI·gaze overlay 명시적 활성화 (`true`)

## Demo 3-C local actual-camera smoke

[`DEMO_3C_REAL_CAMERA_SMOKE.md`](DEMO_3C_REAL_CAMERA_SMOKE.md)는 physical
browser camera → Eye worker → Gateway → API → explicitly opt-in static AOI →
test-only deterministic Top 1을 위한 loopback-only 수동 smoke 절차다. 이는
production acceptance가 아니며, fake media device·Luna·Supabase를 사용하지
않는다.

테스트 API는 Supabase에도 등록된 검수 완료 v4 상품·matching profile을 메모리에서
사용한다. 결과 화면은 `카메라 테스트 완료`로 표시하여 실제 Luna 추천과 구분한다.

기본 보정은 25점 가변 수집 + 독립 8점 확인이다. 점 주변의 링은 유효 샘플로 채워지고,
Worker가 충분히 수집한 뒤 다음 표적으로 이동한다. 일부 지점만 최대 4점 보완하며,
전체 64초/128초 타이머와 자동 전체 재시도는 사용하지 않는다. 효과음은 기본 꺼짐이다.

‘얼굴 맞추기 시작’ 후 같은 카메라 스트림의 미리보기와 타원 가이드를 표시한다.
Eye에서 양쪽 눈·얼굴 위치·상대 크기·각도를 확인하면 초록색으로 바뀌며 약 1초 안정 후
자동으로 시선 맞추기를 시작한다. 준비 실패는 30초 안에 안내하며 새 카메라 권한 요청이나
두 번째 스트림을 만들지 않는다. `/calibration-preview.html`에서 얼굴 미인식·거리·각도와
준비 완료 상태를 모의 확인할 수 있다. 실제 얼굴 인식은 로컬 live 경로에서 따로 확인한다.

[로컬 보정 v2와 A/B/C 절차](../../docs/eye-calibration-local-v2.md)에
`VITE_CALIBRATION_PROFILE`의 25점·16점·고정 비교 설정과 카메라 없는
`/calibration-preview.html` 화면 점검 방법을 정리했다. 프레임은 실제 표적 도착 후의
표시 시각을 사용한다. 품질 미달·얼굴 미검출도 영상으로 진행하며, 약한 신호는 낮은
신뢰도로 전달한다. 관측이 하나라도 있으면 API가 Luna Medium으로 상품을 선택하고,
Kiosk는 해당 AI 결정의 상품을 표시한다. 컬렉션 첫 상품으로 대체하는 경로는 없다.
상품에 연결되지 않은 관측도 품질·결측과 함께 AI에 전달하며, 고객 문구는 실제 주시 지점이나
취향을 단정하지 않는다. 관측 0개·취소·API 오류를 정상 분석으로 바꾸지 않는다.

실제 Luna 로컬 실행은 저장소 루트의 `scripts/run_local_submission_stack.ps1`을 사용한다.
`-ValidateOnly`는 외부 호출 없이 설정·프롬프트·검수된 상품 10개를 검사한다. 실제 실행은
15173/8000/8765/8766 포트를 사용하므로 기존 카메라 테스트 스택을 먼저 종료한다.
이 스크립트는 기존 서버 전용 키를 재사용하고 DB 대신 검수된 v4 상품 스냅샷을 사용한다.

저장소 루트에서 Node.js `24.19.0`과 npm을 사용한다.

```powershell
npm install
npm run dev:kiosk
```

변경 후 검증한다.

```powershell
npm test --workspace @mkk/kiosk
npm run lint --workspace @mkk/kiosk
npm run build --workspace @mkk/kiosk
```

## 개발용 영상 좌표 overlay

S03 룩북 화면은 기본적으로 시선을 따라가는 점을 표시하지 않는다. 개발 검증이 필요한 경우에만 `VITE_KIOSK_DEBUG_AOI=true`로 최신 gaze 위치를 실제 영상 content 영역 위에 표시한다. gaze는 해당 frame의 캡처 시점 `VideoLayout`으로 video 정규화 좌표에 매핑한다.

- `valid=false`와 `outside_video`를 별도 상태로 표시하고 좌표나 상품 후보로 대체하지 않는다.
- Kiosk overlay는 AOI hit나 상품 후보를 계산하지 않고 `BACKEND AOI PENDING`만 표시한다.
- 개발·release 빌드 모두 overlay는 기본 비활성화이며 `VITE_KIOSK_DEBUG_AOI=true`일 때만 활성화된다.
- overlay는 디버그 표시만 담당하며 중앙 추천 v2의 S04 Top 1 결과와 Manager 요청 흐름을 변경하지 않는다.
- 원본 frame, image bytes, base64와 얼굴 embedding을 파일·DB·API·로그·브라우저 저장소에 추가하지 않는다.
