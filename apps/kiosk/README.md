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
