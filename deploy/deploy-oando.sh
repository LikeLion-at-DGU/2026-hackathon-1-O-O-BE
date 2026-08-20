#!/usr/bin/env bash
# GitHub Actions가 SSH로 호출하는 배포 스크립트.
#
# 배치: sudo cp /srv/oando/deploy/deploy-oando.sh /usr/local/sbin/deploy-oando
#       sudo chmod 755 /usr/local/sbin/deploy-oando
# 서버의 /usr/local/sbin/deploy-oando는 이 파일의 사본이어야 한다 — 서버에서만
# 고치면 다음 사람이 레포만 보고 배포를 재현할 수 없다.
#
# root로 실행되지만 git·python은 oando 계정으로 내린다. root가 /srv/oando에서
# git을 직접 돌리면 소유자가 달라 dubious ownership 오류가 난다. safe.directory를
# root에 심는 대신 소유자 계정으로 실행하는 쪽이 원인을 정확히 푸는 방법이다.

set -euo pipefail

APP_DIR=/srv/oando
APP_USER=oando

cd "$APP_DIR"

sudo -u "$APP_USER" git pull --ff-only
sudo -u "$APP_USER" ./venv/bin/pip install --quiet -r requirements.txt
sudo -u "$APP_USER" ./venv/bin/python manage.py migrate --noinput
sudo -u "$APP_USER" ./venv/bin/python manage.py collectstatic --noinput

# 재시작하면 진행 중인 리포트·화보 생성 스레드가 사라진다(daemon thread).
# 데모 중에는 생성 작업이 없는 순간에만 배포를 트리거한다.
systemctl restart oando
systemctl is-active --quiet oando && echo "deploy ok: oando active"
