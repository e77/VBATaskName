#!/usr/bin/env sh
set -euo pipefail

: "${POSTGRES_USER:=spool}"
: "${POSTGRES_PASSWORD:=spoolpass}"
: "${POSTGRES_DB:=spooldb}"
: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${BACKUP_INTERVAL:=86400}"

export PGPASSWORD="$POSTGRES_PASSWORD"

mkdir -p /backup/dumps

while true; do
  ts=$(date -u +"%Y%m%dT%H%M%SZ")
  file="/backup/dumps/${POSTGRES_DB}-${ts}.sql.gz"
  echo "[backup] writing ${file}" >&2
  if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$file"; then
    echo "[backup] completed" >&2
  else
    echo "[backup] failed" >&2
  fi
  sleep "$BACKUP_INTERVAL"
done
