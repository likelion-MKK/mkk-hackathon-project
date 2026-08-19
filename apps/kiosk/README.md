# Kiosk App

## 책임과 현재 경계

조윤혜가 S01–S04 화면, 영상·웹캠 orchestration과 Backend 연결을 담당한다. 공유 Vision·추천 계약은 박형진·양유상·정은미와 함께 리뷰한다.

기본 실행은 실제 FastAPI에 연결하는 중앙 추천 v2 transport다. 원격 Vision은 [`ADR-0001`](../../docs/adr/0001-remote-vision-inference.md)이 Proposed인 동안 실제 고객에게 사용하지 않으며, 현재 Vision producer는 개발 검증용 local/in-process replay다. 원본 frame·image bytes·base64·embedding·원본 경로는 REST payload, 브라우저 저장소, 로그나 추천 AI 입력에 포함하지 않는다.

## Real HTTP v2 흐름

```text
S01 대기 → S02 가방 룩북 선택·동의 → 보정 → S03 약 60초 룩북
  → 4Hz 분석 frame의 시선·표정 파생값을 frame_id로 결합
  → POST /api/v2/sessions/{id}/observations
  → POST /api/v2/sessions/{id}/complete
  → GET /api/v2/sessions/{id}/recommendation REST polling
  → completed인 경우에만 DB의 MCM 가방 10개 중 Top 1 표시
  → 고객이 버튼을 누른 경우에만 v2 manager-product-request 전송
```

real mode는 `mcm-central-ai-replay-v2` manifest와 v2 계약을 사용한다. 동일 `frame_id`와 capture sequence의 Eye·Face 신호를 먼저 결합하고, 원래 frame sequence와 frame-drop gap을 보존한다. 같은 frame의 sequence가 충돌하면 임의 선택하지 않고 실패한다. 누락·무효 modality는 `null + reason`으로 유지한다. seek·`playback_epoch` 변경·결측·무효·out-of-order·1초 초과 gap에서는 이동, 변화율과 지속 상태를 초기화한다. 초기화 직후 계산할 수 없는 이동·변화값을 0으로 만들지 않는다. 겹치는 여러 AOI는 특정 상품의 복귀 근거로 임의 귀속하지 않는다.

Kiosk의 분석 cadence는 250ms 간격인 4Hz다. 60초 세션은 약 240 observation을 만들며 v2 batch 상한 256 안에 들어간다. frame drop이나 modality 차이로 상한을 넘으면 모든 observation을 보존한 채 다음 batch로 분할한다.

## 고객 설명과 상품 자산

S04는 `completed` 결과의 단일 `selected_product_id`만 표시한다. `insufficient_data`와 `failed`는 추천 성공처럼 대체하지 않고 명시적인 오류 화면으로 보낸다. 고객의 명시적 매니저 요청은 `session_id + recommendation_id` 기반의 안정적인 `request_id`를 재사용해 응답 유실 후 재시도도 중복 이벤트가 되지 않게 한다.

고객 문구는 AI 자유 문장을 그대로 표시하지 않는다. 서버가 검증한 `exploration_tendency_code`, `reason_codes`와 DB의 `controlled_tags`를 Frontend allowlist 템플릿에 매핑한다. 감정·성격·심리 유형이나 구매 의도를 단정하지 않는다.

개별 상품은 `source_status=team_approved_catalog_record`이고 `approved_asset=true`일 때만
상세 정보와 `assets/products/<product_id>.jpeg`, `assets/qr/<product_id>/official-product.png`를 각각
`/media/products/<product_id>.jpeg`, `/media/qr/<product_id>/official-product.png`로 변환해 표시한다. QR은
해당 상품의 검수된 `official_product_url`을 직접 인코딩한 정적 PNG다. 경로가 product ID와
일치하지 않거나 상품 이미지 로드에 실패하면 임의 placeholder 상품 이미지로 대체하지 않고
준비 중 상태를 보존한다. 공식 상품 URL이 없으면 링크와 Manager 요청을 숨기며, QR 로드만
실패하면 상품 상세는 유지하고 QR만 숨긴다.

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
- `VITE_VISION_MODE=replay`: 승인 전 local/in-process replay producer
- `VITE_LOOKBOOK_ID=mcm-central-ai-replay-v2`: canonical 가방 룩북
- `VITE_LOOKBOOK_VIDEO_URL`: 승인된 룩북 영상 URL
- `VITE_KIOSK_DEBUG_AOI`: 개발용 AOI·gaze overlay 명시적 활성화 (`true`)

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

## D04 개발용 AOI overlay

S03 룩북 화면은 개발 검증을 위해 현재 `video_time_ms`에 활성화된 manifest exposure polygon과 최신 gaze 위치를 실제 영상 content 영역 위에 표시한다. gaze는 해당 frame의 캡처 시점 `VideoLayout`으로 video 정규화 좌표에 매핑한다.

- `valid=false`와 `outside_video`를 별도 상태로 표시하고 좌표나 상품 후보로 대체하지 않는다.
- AOI hit 여부는 기존 `LookbookManifest`와 시선 파생 신호로만 계산한다.
- 개발 빌드에서는 overlay가 기본 활성화되며, release 빌드는 `VITE_KIOSK_DEBUG_AOI=true`일 때만 활성화된다.
- overlay는 디버그 표시만 담당하며 중앙 추천 v2의 S04 Top 1 결과와 Manager 요청 흐름을 변경하지 않는다.
- 원본 frame, image bytes, base64와 얼굴 embedding을 파일·DB·API·로그·브라우저 저장소에 추가하지 않는다.
