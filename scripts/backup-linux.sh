#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$project_dir/backups"
docker compose -f "$project_dir/compose.yaml" stop app
tar -C "$project_dir" -czf "$project_dir/backups/tracker-$stamp.tar.gz" data/tracker.db data/secret.key data/session.key
docker compose -f "$project_dir/compose.yaml" start app
echo "$project_dir/backups/tracker-$stamp.tar.gz"

