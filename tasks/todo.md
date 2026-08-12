# 백엔드 초기 세팅 (tasks/결정사항.md 기준)

## 1. 프로젝트 골격
- [x] `oando/` 디렉토리 + venv + 패키지 설치
- [x] `requirements.txt` · `.env.example` · `.gitignore` · `README.md`
- [x] `config/` — settings(SQLite WAL) · urls · asgi · wsgi
- [x] 앱 6개 생성: `visits` `catalog` `events` `chat` `analysis` `dashboard`
- [x] `api/` — authentication · exceptions · v1/urls
- [x] `common/ids.py` (privacy·llm은 실제로 쓰는 시점에 만든다)

## 2. 모델 (마이그레이션 전에 확정)
- [x] `visits`: Visitor, Visit(token, last_seen_at, ended_at)
- [x] `catalog`: Store, Scene, Product(8축 컬럼 + TextChoices)
- [x] `events`: Event(append-only, event_id unique)
- [x] `chat`: ChatLog(role choices)
- [x] `analysis`: TasteProfile, Report(status pending/ready/failed)
- [x] `dashboard`: 모델 없음 (기본 User 사용)

## 3. 기반 설정
- [x] `AUTH_USER_MODEL` 건드리지 않음 · simplejwt는 `/admin/*`만
- [x] DRF 기본 권한 잠그고 공개 엔드포인트만 열기
- [x] 공통 에러 포맷 핸들러 `{"error":{code,message,detail}}`
- [x] drf-spectacular `/api/schema/swagger-ui/`
- [x] SQLite WAL + timeout + 짧은 트랜잭션 원칙

## 4. 검증 (완료 정의)
- [x] `makemigrations --check --dry-run` 통과
- [x] `migrate` 성공
- [x] `runserver` 에러 없이 기동
- [x] `/api/schema/` · `/api/schema/swagger-ui/` 실제 호출 확인
- [x] `POST /admin/auth` 성공 200 · 인증 실패 401 · 검증 실패 400 · 없는 경로 404 실제 호출 확인

## 다음 단계 (이번 세팅 범위 밖)
- [ ] `POST /enter` + 이어하기 + 시드 데이터 30개
- [ ] `GET /products/{id}` · `POST /events` · `/chat/messages` · `/chat`(SSE)
- [ ] `/finish` → 워커(threading) → `/reports/{slug}`
- [ ] `/admin/funnel` · `/admin/products` (`/admin/auth`는 완료)
