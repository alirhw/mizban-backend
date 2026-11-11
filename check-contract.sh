#!/usr/bin/env bash
# Contract check: boot the dev server on a scratch port, fetch the live
# OpenAPI document from /api/v1/openapi.json and compare it with
# api/openapi.snapshot.json. The snapshot is created on the first run;
# afterwards any drift fails the check (exit 1).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${CONTRACT_PORT:-8137}"
SNAPSHOT="api/openapi.snapshot.json"
TMP="$(mktemp)"
PRETTY="$(mktemp)"

python manage.py runserver "127.0.0.1:${PORT}" --noreload > /tmp/mizban-contract-server.log 2>&1 &
SERVER_PID=$!
cleanup() { kill "${SERVER_PID}" 2>/dev/null || true; rm -f "${TMP}" "${PRETTY}"; }
trap cleanup EXIT

ok=""
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/api/v1/openapi.json" -o "${TMP}"; then ok=1; break; fi
  sleep 1
done
if [ -z "${ok}" ]; then
  echo "ERROR: API server did not come up; see /tmp/mizban-contract-server.log" >&2
  exit 1
fi

python -m json.tool "${TMP}" > "${PRETTY}"

if [ ! -f "${SNAPSHOT}" ]; then
  cp "${PRETTY}" "${SNAPSHOT}"
  echo "Created ${SNAPSHOT} on first run - commit it."
  exit 0
fi

SNAP_PRETTY="$(mktemp)"
trap 'kill "${SERVER_PID}" 2>/dev/null || true; rm -f "${TMP}" "${PRETTY}" "${SNAP_PRETTY}"' EXIT
python -m json.tool "${SNAPSHOT}" > "${SNAP_PRETTY}"
if diff -u "${SNAP_PRETTY}" "${PRETTY}" > /dev/null; then
  echo "OpenAPI contract unchanged."
else
  echo "OpenAPI contract DRIFT vs ${SNAPSHOT}:" >&2
  diff -u "${SNAP_PRETTY}" "${PRETTY}" | head -100 >&2 || true
  exit 1
fi
