#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend_dir="$repo_root/frontend"
commit="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
output="${1:-$repo_root/dist/hy-agent-frontend-overlay-$commit.tar.gz}"
stage="$(mktemp -d)"

cleanup() {
  rm -rf "$stage"
}
trap cleanup EXIT

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  (
    cd "$frontend_dir"
    NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api}" \
      NEXT_PUBLIC_ASSISTANT_ID="${NEXT_PUBLIC_ASSISTANT_ID:-hy-chat}" \
      NEXT_PUBLIC_BACKEND_URL="${NEXT_PUBLIC_BACKEND_URL:-/backend}" \
      NEXT_PUBLIC_CHAT_RUN_TIMEOUT_MS="${NEXT_PUBLIC_CHAT_RUN_TIMEOUT_MS:-180000}" \
      pnpm build
  )
fi

for required in \
  "$frontend_dir/.next/standalone/server.js" \
  "$frontend_dir/.next/static" \
  "$frontend_dir/public"; do
  if [[ ! -e "$required" ]]; then
    echo "Missing frontend build output: $required" >&2
    exit 1
  fi
done

mkdir -p \
  "$stage/release/standalone" \
  "$stage/release/static" \
  "$stage/release/public" \
  "$(dirname "$output")"

# Keep the release architecture-neutral. The production image already contains
# the lockfile-matched Linux node_modules tree; only application output changes.
tar -C "$frontend_dir/.next/standalone" \
  --exclude="./node_modules" \
  -cf - . | tar -C "$stage/release/standalone" -xf -
tar -C "$frontend_dir/.next/static" -cf - . | \
  tar -C "$stage/release/static" -xf -
tar -C "$frontend_dir/public" -cf - . | \
  tar -C "$stage/release/public" -xf -

cp "$repo_root/deploy/ecs/Dockerfile.frontend-overlay" "$stage/release/"
shasum -a 256 "$frontend_dir/pnpm-lock.yaml" | awk '{print $1}' \
  > "$stage/release/pnpm-lock.sha256"
printf '%s\n' "$commit" > "$stage/release/git-commit"

tar -C "$stage/release" -czf "$output" .
shasum -a 256 "$output"
du -h "$output"
