# SSE 스트리밍 때문에 ASGI(uvicorn)로 띄운다. gunicorn(WSGI)이면 청크가 버퍼링되어
# 챗봇 응답이 한 번에 나가고, 로컬 runserver에서는 되는데 배포하면 안 되는 상태가 된다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput

# 워커 1개인 이유: SQLite는 쓰기가 DB 전체를 잠그고, 화보 폴링 상태를 LocMem 캐시에
# 두면 프로세스마다 캐시가 따로 논다(= 폴링 404). Postgres + Redis를 붙인 뒤에만 늘린다.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
