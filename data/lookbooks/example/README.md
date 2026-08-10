# 예제 Lookbook 데이터

`manifest.json`은 Contract v1 검증과 AOI Mapper 개발에 사용하는 가상 fixture입니다. 실제 MCM 룩북 영상이나 확정 상품 배치를 나타내지 않습니다.

- 좌표 공간: 영상 content 기준 `0.0~1.0` 정규화 좌표
- 시간 구간: `start_ms <= video_time_ms < end_ms`
- 상품 참조: `data/products/catalog.example.json`의 `P001`, `P002`

실제 룩북을 연결할 때는 영상의 고정 version과 상품 ID를 확인한 뒤 별도 디렉터리와 새 `manifest_version`을 사용합니다.
