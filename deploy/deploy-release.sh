#!/usr/bin/env bash

set -Eeuo pipefail
umask 027

readonly mcm_root="/srv/mcm"
readonly releases_root="$mcm_root/releases"
readonly incoming_root="$mcm_root/incoming"
readonly shared_env="$mcm_root/shared/deploy.env"
readonly current_link="$mcm_root/current"
readonly public_url="https://yangyu.cloud"

release_id="${1:-}"
revision="${2:-}"
release_path=""
previous_release=""
switched=0

log() {
  printf '[deploy] %s\n' "$*"
}

run_compose() {
  local target_release="$1"
  shift
  local target_id
  target_id="$(basename "$target_release")"
  MCM_RELEASE_ID="$target_id" docker compose \
    --env-file "$target_release/deploy/.env" \
    --file "$target_release/deploy/docker-compose.yml" \
    --project-name deploy \
    "$@"
}

wait_until_ready() {
  local attempt
  for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 10 \
      "$public_url/readyz" > /dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

rollback() {
  local exit_code="${1:-1}"
  trap - ERR INT TERM
  set +e

  if [[ "$switched" -eq 1 && -n "$previous_release" && -d "$previous_release" ]]; then
    log "deployment failed; restoring $previous_release"
    ln -sfn "$previous_release" "$current_link"
    run_compose "$previous_release" up -d
    if wait_until_ready; then
      log "rollback completed"
    else
      log "rollback started, but readiness did not recover automatically"
    fi
  else
    log "deployment stopped before service switch; current release was not changed"
  fi

  exit "$exit_code"
}

trap 'rollback $?' ERR
trap 'rollback 130' INT TERM

if [[ ! "$release_id" =~ ^[0-9a-f]{40}-[0-9]+-[0-9]+$ ]]; then
  log "invalid release id"
  exit 64
fi
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  log "invalid commit revision"
  exit 64
fi

readonly archive_path="$incoming_root/$release_id.tar.gz"
release_path="$releases_root/$release_id"

test -f "$archive_path"
test -f "$shared_env"
test ! -e "$release_path"

previous_release="$(readlink -f "$current_link")"
if [[ "$previous_release" != "$releases_root/"* || ! -d "$previous_release" ]]; then
  log "current release does not resolve inside $releases_root"
  exit 65
fi

log "preparing release $release_id from commit $revision"
install -d -m 0755 "$release_path"
tar --extract --gzip --file "$archive_path" --directory "$release_path" \
  --no-same-owner --no-same-permissions

test -f "$release_path/deploy/docker-compose.yml"
test -f "$release_path/deploy/Caddyfile"
install -m 0600 "$shared_env" "$release_path/deploy/.env"
printf '%s\n' "$revision" > "$release_path/DEPLOYED_COMMIT"

log "validating and building release images"
run_compose "$release_path" config --quiet
run_compose "$release_path" build

log "switching current release"
ln -sfn "$release_path" "$current_link"
switched=1
run_compose "$release_path" up -d

wait_until_ready
curl --fail --silent --show-error --max-time 10 "$public_url/" > /dev/null
media_status="$(curl --silent --show-error --max-time 10 \
  --range 0-0 --output /dev/null --write-out '%{http_code}' \
  "$public_url/media/mcm-lookbook-v2.mp4")"
test "$media_status" = "206"

expected_services="$(run_compose "$release_path" config --services | sort)"
running_services="$(run_compose "$release_path" ps --services --status running | sort)"
test "$running_services" = "$expected_services"

rm -f -- "$archive_path"
log "release $release_id is healthy at commit $revision"
