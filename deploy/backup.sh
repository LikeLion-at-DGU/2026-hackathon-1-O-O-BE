#!/usr/bin/env bash
# 가비아 서버는 8/28 23:59에 통보 없이 삭제된다. 데모가 끝나면 바로 이걸 돌린다.
#
#   bash deploy/backup.sh
#   → /srv/oando/backups/oando-20260828-1830.tar.gz 생성
#
# 만들어진 파일은 서버 밖으로 반드시 내려받는다. 서버에만 두면 같이 사라진다.
#   scp ubuntu@<서버IP>:/srv/oando/backups/oando-*.tar.gz .

set -euo pipefail

APP_DIR=/srv/oando
BACKUP_DIR="$APP_DIR/backups"
STAMP=$(date +%Y%m%d-%H%M)
ARCHIVE="$BACKUP_DIR/oando-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

# WAL 모드라 db.sqlite3만 복사하면 최근 쓰기가 -wal 파일에 남아 유실된다.
# .backup은 WAL을 포함한 일관된 스냅샷을 만든다.
sqlite3 "$APP_DIR/db.sqlite3" ".backup '$BACKUP_DIR/db-$STAMP.sqlite3'"

tar -czf "$ARCHIVE" \
    -C "$BACKUP_DIR" "db-$STAMP.sqlite3" \
    -C "$APP_DIR" media .env

rm "$BACKUP_DIR/db-$STAMP.sqlite3"

echo "백업 완료: $ARCHIVE"
ls -lh "$ARCHIVE"
echo
echo "이제 로컬에서 내려받으세요:"
echo "  scp ubuntu@<서버IP>:$ARCHIVE ."
