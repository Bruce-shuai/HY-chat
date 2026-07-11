#!/usr/bin/env bash
set -euo pipefail

TOKEN="${HY_CHAT_ACCESS_TOKEN:?Set HY_CHAT_ACCESS_TOKEN before running smoke_test.sh}"
AUTH_HEADER="Authorization: Bearer ${TOKEN}"

curl --fail-with-body http://localhost:8000/health

echo
curl --fail-with-body http://localhost:8000/models -H "${AUTH_HEADER}"

echo
curl --fail-with-body http://localhost:8000/tools -H "${AUTH_HEADER}"

echo
curl --fail-with-body http://localhost:8000/rag/formats

echo
curl --fail-with-body -X POST http://localhost:8000/coding-agent/runs \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{"task":"分析这个项目结构，并说明主要文件作用","workspace":"/workspace"}'

echo
curl --fail-with-body http://localhost:8000/coding-agent/runs -H "${AUTH_HEADER}"

echo
curl --fail-with-body http://localhost:8000/images/capabilities -H "${AUTH_HEADER}"

echo
curl --fail-with-body -X POST http://localhost:8000/images/generations \
  -H "${AUTH_HEADER}" \
  -F 'prompt=HY-chat smoke test' \
  -F 'provider=mock'

if [[ "${RUN_MODEL_SMOKE:-false}" == "true" ]]; then
  echo
  curl --fail-with-body -N -X POST http://localhost:8000/chat/stream \
    -H "${AUTH_HEADER}" \
    -H 'Content-Type: application/json' \
    -d '{"message":"只回复 SSE_OK","use_cache":false}'
fi
