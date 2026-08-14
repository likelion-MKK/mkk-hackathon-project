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

Mock 화면 흐름은 `screensaver → menu → consent → calibration → lookbook → finalizing → report` 순서다. `lookbook`과 `finalizing`은 D1 임시 화면이며 실제 영상·추천 UI는 후속 단계에서 연결한다.

D1 Mock 룩북에는 별도의 영상 layout 정보가 없으므로 Mock 시선의 화면 정규화 좌표를 영상 정규화 좌표로 동일하게 취급한다. 이후 manifest의 노출 시간과 polygon AOI를 적용해 `ProductAttentionEvent`로 변환하고, 표정 신호와 함께 `ReactionBatch`에 담는다. 실제 영상 연결 시에는 캡처 시점의 layout을 사용한 좌표 변환으로 교체한다.

카테고리 선택값은 세션의 Mock `lookbook_id`에 반영된다. 가방, 의류, 액세서리는 각각 해당 카테고리의 manifest와 Top 2를 반환하고, 전체 컬렉션은 여러 카테고리 상품을 섞은 manifest와 Top 2를 반환한다. 추천 순위는 실제 알고리즘 결과가 아니라 D1 흐름 검증을 위한 카테고리별 고정 Mock 값이다.

`RESTART`는 진행 중인 flow 세대를 즉시 무효화하고 Vision 작업을 직렬화해 이전 세션의 시작·보정·추론·종료가 새 세션과 겹치지 않도록 한다. 각 API·Vision 비동기 단계 사이에서도 현재 flow인지 다시 확인하며, 무효화된 세션은 이후 batch 전송·분석 완료·화면 전환을 진행하지 않는다.

## D2 동의·취소·timeout Mock 흐름

S02 동의 화면은 카메라 사용, 원격 Vision 서버로의 일시 전송, 원본 frame 비저장, 파생 신호·추천 결과의 이용 목적을 구분해 안내한다. `동의하고 계속`을 누르기 전에는 Mock 세션과 Vision 세션을 시작하지 않는다. D2에서는 실제 카메라나 원격 stream을 열지 않는다.

- `카테고리 다시 선택`: 세션을 만들지 않고 S02 메뉴로 돌아간다.
- `동의하지 않고 종료`: 진행 중 flow를 무효화하고 S01로 돌아간다.
- 동의 대기 30초 초과: 세션을 만들지 않고 timeout 안내와 재시작 선택지를 표시한다.
- Mock 세션 준비 5초 초과: manifest 조회·세션 생성 요청·Vision 시작에 취소 신호를 보내고 timeout 안내와 재시도 선택지를 표시한다. timeout되거나 화면을 떠난 진행 중 요청은 늦게 Mock 세션을 만들지 않는다.

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
