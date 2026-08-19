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

개별 상품 URL·이미지·QR이 검수 전 `null + reason`이면 bundled 가방 placeholder와 공식 전체 가방 listing 링크를 사용한다. 이미지나 QR이 준비된 것처럼 표시하지 않는다.

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

실제 Kiosk 보정 화면은 browser viewport 전체를 기준으로 초기 Dense5의 25개 학습점과
8개 확인점을 부드럽게 이동시킨다. 한 시도의 점 수집 계획은 64초이며, 실패할 때 전체
과정을 한 번 재시도한다(수집 128초와 로컬 처리 시간).

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

S03 룩북 화면은 개발 검증을 위해 최신 gaze 위치를 실제 영상 content 영역 위에 표시한다. gaze는 해당 frame의 캡처 시점 `VideoLayout`으로 video 정규화 좌표에 매핑한다.

- `valid=false`와 `outside_video`를 별도 상태로 표시하고 좌표나 상품 후보로 대체하지 않는다.
- Kiosk overlay는 AOI hit나 상품 후보를 계산하지 않고 `BACKEND AOI PENDING`만 표시한다.
- 개발 빌드에서는 overlay가 기본 활성화되며, release 빌드는 `VITE_KIOSK_DEBUG_AOI=true`일 때만 활성화된다.
- overlay는 디버그 표시만 담당하며 중앙 추천 v2의 S04 Top 1 결과와 Manager 요청 흐름을 변경하지 않는다.
- 원본 frame, image bytes, base64와 얼굴 embedding을 파일·DB·API·로그·브라우저 저장소에 추가하지 않는다.
