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
    OPENAI_API_KEY=(str, ""),
    OPENAI_MODEL=(str, "gpt-4o-mini"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-insecure-key-change-me")
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

# SQLite. WAL로 읽기·쓰기가 서로를 막지 않게 하고, 리포트 워커(스레드)와의
# 쓰기 충돌은 timeout 재시도 + IMMEDIATE 트랜잭션으로 흡수한다.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
        },
    }
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

# 매장은 하나로 고정한다. 클라이언트가 매장을 지정하지 않고 서버가 이 값을 붙인다.
DEFAULT_STORE_ID = env("DEFAULT_STORE_ID", default="s_mcm")

OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_MODEL = env("OPENAI_MODEL")  # 모델 교체는 .env에서만 한다

# 도메인 규칙 (매직 넘버 방지)
RESUME_WINDOW = timedelta(minutes=30)  # 미종료 Visit을 이어받아 주는 시간
DWELL_MAX_MS = 300_000  # 클라이언트가 보낸 체류시간 상한 (탭 백그라운드 방어)
CHAT_TIMELINE_LIMIT = 200  # GET /chat/messages가 한 번에 주는 최대 메시지 수

# 화보 생성 진행 상태는 휘발성이라 DB가 아니라 캐시에 둔다. 폴링이 화보당 8~9번이라
# 그대로 DB에 붙이면 전부 같은 답을 가져오는 조회가 초당 수십 번 발생한다.
# ⚠️ LocMem은 프로세스마다 따로 논다. uvicorn을 --workers 2 이상으로 띄우면
#    폴링이 다른 프로세스에 붙어 404가 나므로, 그때는 Redis 백엔드로 바꿔야 한다.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "lookbook-jobs",
    }
}
LOOKBOOK_JOB_TTL_SEC = 300  # 폴링이 끝나고도 잠깐 남을 만큼만
# 진행률 보간의 분모. ⚠️ 이미지 생성 벤더 실측 p50으로 교체해야 한다.
# 25초로 가정했는데 실제가 40초면 90%에서 오래 멈춰 있는 화면이 된다.
LOOKBOOK_EXPECTED_SEC = env.int("LOOKBOOK_EXPECTED_SEC", default=25)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
