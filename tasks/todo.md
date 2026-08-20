# F8. `POST /api/v1/visits/{visit_id}/finish` + AI② 워커

기준: Notion `관람 종료 & 리포트 생성 (AI ②)`(2026-08-12 최신본) · `tasks/결정사항.md`
범위: **이 페이지만.** `GET /reports/{slug}`(F10)는 별도 페이지라 제외.

## 로컬 export(v0.4)와 달라진 계약 4건

- [x] 바디에 `events[]` 선택 수용 — 종료 직전 버퍼가 `/events`로 가면 401을 맞고 사라진다
- [x] 응답 202에 `events: {accepted, duplicated}` 포함
- [x] path `visit_id`가 토큰의 방문과 다르면 `403`
- [x] LLM은 **1회만** 호출 (취향 추출 + 문장 생성을 한 JSON으로). 대화 없으면 아예 건너뜀
- [x] ⑦단계에서 `characters` 조회로 캐릭터 이미지 매핑 (사전 제작 16장)

## 모듈 분리

- [x] `common/llm.py` — `complete_json()` 게이트웨이 (모델명·타임아웃·재시도 한 곳)
- [x] `analysis/collect.py` — ① DB → 순수 자료구조
- [x] `analysis/pipeline.py` — ②③④⑤ 순수 함수 (DB 접근 없음)
- [x] `analysis/character.py` — ⑥ 4축 결정론적 매핑
- [x] `analysis/scoring.py` — 가중치 상수
- [x] `analysis/insight.py` — LLM 1회 호출 + 실패 시 폴백
- [x] `analysis/report.py` — ⑦ payload 조립 (상품 스냅샷 박제)
- [x] `analysis/services.py` — 한 트랜잭션(이벤트→종료→큐) + 스레드 워커
- [x] `analysis/models.py` — `Character` 추가, `TasteProfile.insight` 추가
- [x] `analysis/{serializers,views,urls,admin}.py`
- [x] `analysis/management/commands/seed_characters.py` — 16유형 임시 문구 시드
- [x] `analysis/tests.py` — 순수 함수 테스트

## 검증

- [x] `makemigrations --check` 통과 · `migrate` 성공 · `runserver` 기동
- [x] 성공: `/finish` 202 + slug + events 집계, 100ms 이내 응답
- [x] 멱등: 같은 visit 재호출 → 같은 slug
- [x] 실패: 토큰 없음 401 · 다른 visit_id 403 · 없는 visit_id 404
- [x] 워커: `status=ready` + payload에 hero·recommendations 8개·상품 스냅샷
- [x] 이벤트 0건 방문에서도 죽지 않음 (`confidence≈0`)
- [x] `ruff check` · `ruff format` 통과

## 보류 (확인 필요)

- [ ] 이탈자 24시간 배치(`is_auto_closed`) — 명세에 있으나 `구조_피드백.md` B-4의 "배치 스케줄러 안 쓴다"와 충돌. `/enter`의 30분 만료가 이미 미종료 Visit을 닫고 있어 중복이다

## 화보 레퍼런스 연결 계획 (코드·서버 변경 전 검토)

- [x] 레퍼런스 자산을 `media/references/`에 배치하고, URL·파일 읽기·`Composition.reference_url` 연결을 서버에서 검증한다.
- [ ] 프론트의 화보 후보 `product_id` 전달과 사진·마스크 업로드 키 전달을 검증해 실제 생성 요청이 202까지 도달하는지 확인한다.
- [ ] 레퍼런스의 그래픽 구조를 최종 합성에 쓸지, AI 스타일 참고에만 쓸지 확정한다.
- [x] 승인된 역할에 따라 `prompts.py`의 이미지 역할 지시를 수정한다. `compose.py` 오버레이 합성은 별도 작업으로 남긴다.

## 화보 생성 장애 해결 시나리오 (진단 우선)

- [x] 서버 자산·권한·외부 접근·`Composition.reference_url`과 AI 설정(`False / ai / gpt-image-2`)을 확인한다.
- [ ] 브라우저 Network에서 생성 POST의 실제 요청 본문·응답(202 또는 오류)을 한 번 확정한다.
- [ ] 서버 DB의 최신 `Lookbook` 상태(`queued` / `processing` / `ready` / `failed`)와 서비스 로그를 같은 작업 ID로 대조한다.
- [ ] 결과에 따라 프론트 요청·폴링·완성 화면 중 한 지점만 최소 수정하고, 실제 생성 1회로 재검증한다.
- [ ] 기능 흐름이 안정된 뒤 레퍼런스별 프롬프트·오버레이 구조를 설계한다. 실제 프롬프트 코드는 별도 승인 뒤에 수정한다.
</content>
</invoke>
