# 중앙 AI 60초 합성 replay manifest

이 디렉터리는 고객 영상이나 승인된 운영 룩북이 아니라 v2 통합 테스트용 결정적
manifest를 보관한다. `manifest.json`은 60초를 6초씩 나눈 10개 단일 상품 구간이며,
상품 ID는 [`mcm-demo-recommendation-profile-v2.json`](../../products/mcm-demo-recommendation-profile-v2.json)의
정확히 10개 ID와 일치한다.

- 각 구간의 full-frame polygon은 합성 Eye·Face replay를 단순화하기 위한 fixture다.
- 실제 영상의 상품 위치·노출 시각·priority를 측정했다는 뜻이 아니다.
- 운영 영상이 승인되면 조윤혜가 영상 시간·좌표를, 박형진이 catalog ID를 검수한 별도
  manifest version을 만든다.
- 원본 frame, 고객 이미지, landmark, embedding 또는 모델 weight를 이 경로에 넣지 않는다.
