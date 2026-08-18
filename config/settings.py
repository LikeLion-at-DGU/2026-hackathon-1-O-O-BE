"""O&O 백엔드 설정. 시크릿은 전부 .env에서 읽는다 (.env.example 참고)."""

from datetime import timedelta
from pathlib import Path

import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000", "http://localhost:5173"]),
    CORS_ALLOW_ALL_ORIGINS=(bool, False),
    CORS_ALLOWED_ORIGIN_REGEXES=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    OPENAI_API_KEY=(str, ""),
    OPENAI_MODEL=(str, "gpt-4o-mini"),
)
environ.Env.read_env(BASE_DIR / ".env")

# 이름을 둘 다 받는다. 배포 문서·튜토리얼마다 SECRET_KEY와 DJANGO_SECRET_KEY가 섞여 있는데,
# 한쪽만 읽으면 값을 넘겨도 조용히 개발용 기본키로 떠서 알아채기 어렵다.
SECRET_KEY = env("DJANGO_SECRET_KEY", default=env("SECRET_KEY", default="dev-only-insecure-key-change-me"))
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "apps.visits",
    "apps.catalog",
    "apps.events",
    "apps.chat",
    "apps.analysis",
    "apps.dashboard",
    "apps.lookbook",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# 로컬은 SQLite, 배포는 DATABASE_URL(Postgres). 코드는 한 벌이고 환경변수만 갈린다.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # SQLite에서만 의미가 있는 설정이다. WAL로 읽기·쓰기가 서로를 막지 않게 하고,
    # 워커와의 쓰기 충돌은 timeout 재시도 + IMMEDIATE 트랜잭션으로 흡수한다.
    DATABASES["default"]["OPTIONS"] = {
        "timeout": 20,
        "transaction_mode": "IMMEDIATE",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
    }

# 관리자만 로그인한다. 사용자는 익명 UUID + visit_token을 쓰므로
# AUTH_USER_MODEL을 커스터마이즈하지 않는다. (매장 1개 고정 → 브랜드 격리 대상 없음)
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
# collectstatic이 모아둘 위치. DEBUG=False에서 django-admin·Swagger의 CSS가 여기서 나간다.
# 앞에 nginx가 있으면 nginx가 서빙하고, 없으면 whitenoise가 대신 서빙한다.
# Manifest 방식은 collectstatic을 빠뜨리면 500이 나므로 데모 안전을 택했다.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # 기본은 잠그고 공개 엔드포인트만 AllowAny로 연다.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["api.authentication.VisitTokenAuthentication"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "EXCEPTION_HANDLER": "api.exceptions.oando_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"chat": "20/min"},  # LLM 남용 방지
    "UNAUTHENTICATED_USER": None,
}

SIMPLE_JWT = {"ACCESS_TOKEN_LIFETIME": timedelta(hours=1)}

SPECTACULAR_SETTINGS = {
    "TITLE": "O&O API",
    "DESCRIPTION": "명품 매장 인터랙티브 리테일 서비스. 사용자 API는 로그인 없이 "
    "X-Anonymous-UUID · X-Visit-Token 헤더를 쓰고, /admin/* 만 Bearer 인증이다.",
    "VERSION": "0.5.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS")  # 로컬 전용. prod에서 켜지 말 것
# 기본 목록(accept·origin·x-requested-with 등)을 덮어쓰면 브라우저 preflight가 깨진다.
CORS_ALLOW_HEADERS = (*default_headers, "x-anonymous-uuid", "x-visit-token")
# Netlify의 PR 미리보기·브랜치 배포는 도메인이 매번 달라진다
# (deploy-preview-3--사이트.netlify.app). 고정 목록으로는 커버가 안 돼서 정규식을 쓴다.
CORS_ALLOWED_ORIGIN_REGEXES = env("CORS_ALLOWED_ORIGIN_REGEXES")

# nginx가 TLS를 끊고 평문으로 넘겨주므로, 이 헤더가 없으면 Django는 자기가 http로
# 서비스된다고 착각한다. Swagger의 서버 주소와 미디어 URL이 http로 나가 mixed content가 된다.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https로 열린 django-admin에서 로그인하려면 Origin이 신뢰 목록에 있어야 한다.
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
# 배포는 https이므로 관리자 세션 쿠키를 평문으로 흘리지 않는다.
# 로컬은 http라서 True로 두면 admin 로그인이 아예 안 된다.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# 매장은 하나로 고정한다. 클라이언트가 매장을 지정하지 않고 서버가 이 값을 붙인다.
DEFAULT_STORE_ID = env("DEFAULT_STORE_ID", default="s_mcm")

OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL")  # 모델 교체는 .env에서만 한다

# 도메인 규칙 (매직 넘버 방지)
# visit_token의 유일한 만료 조건. 진입 시각 기준이며 마지막 활동 기준이 아니다.
# 화보와 재생성이 /finish 이후에 일어나므로 "퇴장 시 즉시 만료"는 폐기했다.
# 3시간이면 관람(20분~1시간) + 화보 + 재생성 3회가 들어가고, 다음날 이어붙기는 막는다.
VISIT_STALE_AFTER = timedelta(hours=3)
DWELL_MAX_MS = 300_000  # 클라이언트가 보낸 체류시간 상한 (탭 백그라운드 방어)
CHAT_TIMELINE_LIMIT = 200  # GET /chat/messages가 한 번에 주는 최대 메시지 수

# 화보 생성 진행 상태는 휘발성이라 DB가 아니라 캐시에 둔다. 폴링이 화보당 8~9번이라
# 그대로 DB에 붙이면 전부 같은 답을 가져오는 조회가 초당 수십 번 발생한다.
# ⚠️ LocMem은 프로세스마다 따로 논다. gunicorn을 --workers 2 이상으로 띄우면 폴링이
#    다른 프로세스에 붙어 404가 나므로, 배포에서는 REDIS_URL을 반드시 채운다.
REDIS_URL = env("REDIS_URL", default="")
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
    if REDIS_URL
    else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "lookbook-jobs"}
}
LOOKBOOK_JOB_TTL_SEC = 300  # 폴링이 끝나고도 잠깐 남을 만큼만
# 진행률 보간의 분모. ⚠️ 이미지 생성 벤더 실측 p50으로 교체해야 한다.
# 25초로 가정했는데 실제가 40초면 90%에서 오래 멈춰 있는 화면이 된다.
LOOKBOOK_EXPECTED_SEC = env.int("LOOKBOOK_EXPECTED_SEC", default=25)
LOOKBOOK_MAX_SELECT = 1  # 화보에 담을 상품 수. 서버가 강제하고 응답으로도 내려준다
LOOKBOOK_MAX_ATTEMPT = 3  # 재생성 횟수. 이미지 생성은 호출당 비용이 붙는다
# 벤더가 붙기 전까지 가짜 결과로 워커·폴링·완료 화면을 실제 경로로 돌린다.
LOOKBOOK_FAKE_AI = env.bool("LOOKBOOK_FAKE_AI", default=True)
LOOKBOOK_FAKE_DELAY_SEC = env.int("LOOKBOOK_FAKE_DELAY_SEC", default=8)
# 화보에 찍히는 고정 문구. 생성 시점에 스냅샷으로 복사되므로 나중에 바꿔도 옛 화보는 그대로다.
LOOKBOOK_VENUE = env("LOOKBOOK_VENUE", default="MCM HAUS SEOUL")
LOOKBOOK_SEASON = env("LOOKBOOK_SEASON", default="2026 F/W")
LOOKBOOK_IMAGE_SIZE = (1080, 1350)  # 인스타그램 세로 비율

# 업로드 — 사진 바이트는 Django를 지나가지 않는다. 서버는 presign URL만 발급한다.
PHOTO_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_URL_TTL_SEC = 600
# 버킷이 정해지기 전까지는 dev. 계약(키·URL·만료)은 그대로 확인되지만 실제 PUT은 받지 않는다.
# 버킷이 생기면 STORAGE_BACKEND=s3 + 아래 4개를 .env에 넣으면 된다 (R2는 S3 호환 API).
# ⚠️ 그때 버킷 CORS(PUT·GET)를 반드시 열 것. 로컬은 same-origin이라 안 걸리고 배포 후에 터진다.
STORAGE_BACKEND = env("STORAGE_BACKEND", default="dev")
STORAGE_ENDPOINT_URL = env("STORAGE_ENDPOINT_URL", default="")
STORAGE_BUCKET = env("STORAGE_BUCKET", default="")
STORAGE_REGION = env("STORAGE_REGION", default="auto")
STORAGE_ACCESS_KEY = env("STORAGE_ACCESS_KEY", default="")
STORAGE_SECRET_KEY = env("STORAGE_SECRET_KEY", default="")
UPLOAD_DEV_BASE_URL = env("UPLOAD_DEV_BASE_URL", default="https://uploads.invalid/dev")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
