#!/usr/bin/env bash
set -euo pipefail

readonly BACKUP_DIR="${BACKUP_DIR:-/opt/backups/hy-chat}"
readonly RETENTION_DAYS="${RETENTION_DAYS:-7}"
readonly TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
readonly OUTPUT="${BACKUP_DIR}/hy-chat-${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

docker exec hy-chat-postgres pg_dump \
  --username=hy_chat \
  --dbname=hy_chat_db \
  --format=custom > "${OUTPUT}"

chmod 600 "${OUTPUT}"
find "${BACKUP_DIR}" -type f -name 'hy-chat-*.dump' \
  -mtime "+${RETENTION_DAYS}" -delete

echo "Created ${OUTPUT}"
