# Kiosk App

## 소유자

조윤혜(FE). Eye·Face 실행 경계, Vision Stream이나 API 계약을 바꿀 때는 박형진·양유상·정은미와 함께 리뷰한다. 원격 추론은 [`ADR-0001`](../../docs/adr/0001-remote-vision-inference.md)이 Accepted된 뒤 실제 고객 frame에 연결한다.

## 로컬 실행

저장소 루트에서 다음 명령으로 실행한다.

```powershell
npm install
npm run dev:kiosk
```

기본 개발 주소는 `http://localhost:5173`이며 Backend 주소는 `.env.example`에서 확인한다.

## D1 로컬 실행과 검증

현재 D1 구현은 실제 Backend·카메라·AI 모델 대신 `MockApiClient`와 `MockVisionClient`를 사용한다.

```powershell
Set-Location apps/kiosk
npm install
npm run dev
```

변경 후에는 같은 디렉터리에서 다음 검증을 모두 실행한다.

```powershell
npm run lint
npm run test
npm run build
```

Mock 화면 흐름은 `screensaver → menu → consent → calibration → lookbook → finalizing → report` 순서다. D04에서는 룩북 영상 위에 개발용 AOI·시선 overlay를 표시하고, `report`에서 catalog 기반 Mock Top 2와 상품별 Mock QR preview를 보여준다. 실제 Vision 결과와 고정 QR asset은 후속 연결 단계에서 교체한다.

D1 Mock 룩북에는 별도의 영상 layout 정보가 없으므로 Mock 시선의 화면 정규화 좌표를 영상 정규화 좌표로 동일하게 취급한다. 이후 manifest의 노출 시간과 polygon AOI를 적용해 `ProductAttentionEvent`로 변환하고, 표정 신호와 함께 `ReactionBatch`에 담는다. 실제 영상 연결 시에는 캡처 시점의 layout을 사용한 좌표 변환으로 교체한다.

D04 개발 환경에서는 현재 `video_time_ms`에 활성화된 manifest exposure polygon과 최신 Mock gaze를 실제 영상 content 영역 위에 겹쳐 표시한다. 시선은 해당 frame의 캡처 layout으로 video 좌표에 매핑하며, `valid=false`와 `outside_video`는 별도 상태로 표시하고 좌표나 상품 후보로 바꾸지 않는다. AOI overlay는 `import.meta.env.DEV`에서 기본 활성화되고 `VITE_KIOSK_DEBUG_AOI=true`로 명시적으로 켤 수 있으며 release 빌드에서는 기본 비활성화된다.

카테고리 선택값은 세션의 Mock `lookbook_id`에 반영된다. 가방, 의류, 액세서리는 각각 해당 카테고리의 manifest와 Top 2를 반환하고, 전체 컬렉션은 여러 카테고리 상품을 섞은 manifest와 Top 2를 반환한다. 추천 순위는 실제 알고리즘 결과가 아니라 D1 흐름 검증을 위한 카테고리별 고정 Mock 값이다.

`RESTART`는 진행 중인 flow 세대를 즉시 무효화하고 Vision 작업을 직렬화해 이전 세션의 시작·보정·추론·종료가 새 세션과 겹치지 않도록 한다. 각 API·Vision 비동기 단계 사이에서도 현재 flow인지 다시 확인하며, 무효화된 세션은 이후 batch 전송·분석 완료·화면 전환을 진행하지 않는다.

## D2 동의·취소·timeout Mock 흐름

S02 동의 화면은 카메라 사용, 원격 Vision 서버로의 일시 전송, 원본 frame 비저장, 파생 신호·추천 결과의 이용 목적을 구분해 안내한다. `동의하고 계속`을 누르기 전에는 Mock 세션과 Vision 세션을 시작하지 않는다. D2에서는 실제 카메라나 원격 stream을 열지 않는다.

MVP 파생 데이터 정책은 선택지 C를 사용한다. 개별 `GazeSample`, `ExpressionSample`, `ProductAttentionEvent`는 현재 세션의 관심도 집계에만 사용하고 PostgreSQL·파일·브라우저 저장소에 보관하지 않는다. D2 Mock API는 `ReactionBatch` payload를 검증한 뒤 폐기하고 수집 중 중복 제거용 batch ID만 메모리에 유지하며, 분석 완료 시 이 ID도 비운다. Kiosk가 보유한 최신 개별 신호 참조도 추천 요청 완료 또는 실패 시 해제한다. 최종 추천 결과와 익명 세션 상태는 현재 세션 화면 제공에 필요한 동안만 메모리에 유지한다. 실제 알고리즘 검증에서 replay 필요성이 확인되기 전에는 파생 event 영속 저장을 활성화하지 않는다.

이 결정은 D2 Mock의 동작과 동의 문구에 적용한 범위다. 현재 `reaction-batch` v1의 영속 저장 의미, 실제 Backend의 세션 집계·TTL과 PostgreSQL 경계는 공용 Contract를 먼저 갱신한 뒤 Producer와 Consumer 순서로 연결해야 하며, 그 전에는 실제 API·Vision client를 연결하지 않는다.

- `카테고리 다시 선택`: 세션을 만들지 않고 S02 메뉴로 돌아간다.
- `동의하지 않고 종료`: 진행 중 flow를 무효화하고 S01로 돌아간다.
- 동의 대기 30초 초과: 세션을 만들지 않고 timeout 안내와 재시작 선택지를 표시한다.
- Mock 세션 준비 5초 초과: manifest 조회·세션 생성 요청·Vision 시작에 취소 신호를 보내고 timeout 안내와 재시도 선택지를 표시한다. timeout되거나 화면을 떠난 진행 중 요청은 늦게 Mock 세션을 만들지 않는다.

실제 API·Vision client 연결 전에는 Backend 세션 취소 API, 세션 생성 멱등성 키와 생성 후 미사용 세션의 TTL 정책을 계약으로 확정해야 한다. Kiosk가 `session_id`를 받은 뒤 Vision 시작이 실패하면 취소 API를 호출하고, 응답을 받지 못한 생성 요청은 Backend TTL로 정리할 수 있어야 한다. 이 계약이 준비되기 전 D2 세션 시작 흐름은 Mock 전용이다.

## D3 커밋 1 영상 재생과 FrameContext

S03의 임시 룩북 영상은 `VITE_LOOKBOOK_VIDEO_URL`로 연결한다. 로컬 파일을 사용할 때는 파일을 `public/` 아래에 두고 `/파일명.mp4`처럼 설정한다. 영상 URL이 비어 있거나 로드에 실패하면 카테고리 포스터와 연결 안내를 표시하며 재생 버튼은 비활성화한다.

플레이어는 재생·일시정지·탐색과 현재 `video_time_ms`를 제공한다. `object-fit: contain`으로 표시한 video element의 위치와 원본 영상 비율을 이용해 letterbox를 제외한 실제 content 영역을 `VideoLayout`으로 계산한다. `FrameContext`는 `session_id`, frame 식별자, 단조 증가 캡처 시각, `video_id`, 캡처 순간의 `video_time_ms`, `playback_epoch`과 layout을 한 번에 복사해 고정한다. 현재 화면에는 PR 2 연결 전 확인용 context preview만 표시한다.

첫 번째 커밋에서는 웹캠 권한, `FrameSource`, 카메라 frame 읽기와 `FakeRemoteVisionClient`를 구현하지 않는다. 해당 경계는 아래 두 번째 커밋에서 연결한다.

## D3 커밋 2 웹캠과 FrameSource

`동의하고 계속`을 누른 뒤에만 브라우저 카메라 권한을 요청한다. audio는 항상 `false`이며 video는 1280×720, 30fps를 선호값으로 요청하되 실제 장치 설정과 같다고 가정하지 않는다. 권한 거부와 장치·시작 실패는 구분해 안내하고 다시 시도할 수 있다.

한 세션은 단일 `FrameSource`만 사용한다. 룩북 재생 중 D3 fake 확인용 250ms 간격으로 최신 camera frame을 읽고, 같은 순간의 `FrameContext`와 함께 `FakeRemoteVisionClient`에 전달한다. 실제 sampling FPS는 D5 성능 검증 후 확정한다. 이전 frame 처리 중에는 새 frame을 쌓지 않고 drop한다. fake client는 네트워크를 열거나 frame을 보관하지 않으며 session·video ID 경계만 확인한다. 임시 `ImageBitmap`은 전달 성공·실패와 관계없이 `FrameSource`가 즉시 `close()`한다.

처음 화면 이동, 동의 취소·timeout, 세션 시작 실패, 보정 실패, 영상 로드 실패, 룩북 종료와 앱 unmount에서 camera track과 video 참조를 해제한다. 초기화 중인 pending stream·video도 즉시 정리하고 취소된 open과 재시도 open을 분리한다. frame consumer에는 취소 신호를 전달하며 consumer 전후 lifecycle을 다시 확인해 화면 종료 뒤 `delivered`로 완료하지 않는다. 실제 WSS, binary encoding, AI 서버와 Eye·Face 모델 연결은 포함하지 않는다.

## 책임

- S01 대기 화면부터 S04 분석 결과 화면까지의 상태 전이를 관리한다.
- 웹캠은 한 번만 열고 캡처 순간의 `FrameContext`와 frame을 `RemoteVisionClient`에 전달한다.
- camera는 video만 요청하고 audio capture·전송은 사용하지 않는다.
- 룩북 재생 시각, `playback_epoch`, viewport와 실제 영상 표시 영역을 캡처 시점에 고정한다.
- 동의된 세션에서만 WSS stream을 열고 in-flight frame `1`, 최신 frame 우선과 전송 상한을 적용한다.
- 개발 모드에서만 시선·AOI·품질 overlay를 표시하고, 세션 종료 시 카메라와 버퍼를 해제한다.

## 입력

- `LookbookManifest`, 상품 정보, 세션·동의 API 응답
- Vision Gateway가 반환한 `GazeSample`·`ExpressionSample`과 추천 상태·`RecommendationResult`
- Fake/Replay Adapter 선택과 debug 표시를 위한 실행 설정

## 출력

- `FrameContext`, `VideoLayout`, 화면 상태와 사용자 이벤트
- Vision Stream v1의 binary frame producer. 일반 REST·event payload에는 frame을 넣지 않음
- 파생 이벤트를 담은 `ReactionBatch`, 세션 완료 요청
- S04의 Top 2 상품 카드와 사전 생성된 상품별 QR 표시

## 금지사항

- 원본 frame을 base64·JSON·일반 REST로 직렬화하거나 파일·로그·브라우저 저장소에 보관하지 않는다. 승인된 동의 세션의 binary WSS transport만 허용한다.
- 동의 전·철회 후·세션 만료 후에는 camera와 Vision stream을 열어 두지 않는다.
- server 실패를 Fake 결과, `(0, 0)` 또는 중립 표정으로 대체하지 않는다.
- 추론 완료 시점의 영상 시간을 캡처 시각 대신 사용하지 않는다.
- Eye/Face 신호가 없을 때 `(0, 0)` 또는 중립 표정으로 대체하지 않는다.
- Kiosk가 추천 가중치나 최종 Top 2를 계산하지 않는다.
