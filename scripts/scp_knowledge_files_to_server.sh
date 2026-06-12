#!/usr/bin/env bash
set -Eeuo pipefail

CONNECT_SCRIPT="${CONNECT_SCRIPT:-connect-server.sh}"
SOURCE_DIR="${SOURCE_DIR:-course-materials-md}"
REMOTE_UPLOAD_ROOT="${REMOTE_UPLOAD_ROOT:-/opt/kb/knowledge-uploads}"
APP_DIR="${APP_DIR:-/opt/kb/knowledge-base-qa-bot}"
LOCAL_ARCHIVE_DIR="${LOCAL_ARCHIVE_DIR:-tmp/knowledge-upload}"

fail() {
  echo "error: $*" >&2
  exit 1
}

require_safe_remote_path() {
  local value="$1"
  local name="$2"

  case "$value" in
    /*) ;;
    *) fail "$name must be an absolute remote path: $value" ;;
  esac

  case "$value" in
    *"'"*) fail "$name must not contain a single quote: $value" ;;
  esac
}

if [ ! -f "$CONNECT_SCRIPT" ]; then
  fail "missing CONNECT_SCRIPT=$CONNECT_SCRIPT"
fi

if [ ! -d "$SOURCE_DIR" ]; then
  fail "missing SOURCE_DIR=$SOURCE_DIR"
fi

require_safe_remote_path "$REMOTE_UPLOAD_ROOT" "REMOTE_UPLOAD_ROOT"
require_safe_remote_path "$APP_DIR" "APP_DIR"

read -r -a connect_parts < "$CONNECT_SCRIPT"
if [ "${#connect_parts[@]}" -lt 2 ] || [ "${connect_parts[0]}" != "ssh" ]; then
  fail "$CONNECT_SCRIPT must contain a simple ssh command, for example: ssh -i ~/.ssh/key root@host"
fi

remote_index=$((${#connect_parts[@]} - 1))
remote="${connect_parts[$remote_index]}"
ssh_args=("${connect_parts[@]:1:$remote_index}")

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
source_base="$(basename "$SOURCE_DIR")"
source_parent="$(cd "$(dirname "$SOURCE_DIR")" && pwd)"

mkdir -p "$LOCAL_ARCHIVE_DIR"
archive_path="$LOCAL_ARCHIVE_DIR/${source_base}-${timestamp}.tar.gz"
remote_dir="$REMOTE_UPLOAD_ROOT/$timestamp"
remote_archive="$remote_dir/${source_base}-${timestamp}.tar.gz"
remote_source="$remote_dir/source"

echo "Creating local knowledge archive: $archive_path"
tar -czf "$archive_path" -C "$source_parent" "$source_base"

echo "Creating remote upload directory: $remote:$remote_dir"
ssh "${ssh_args[@]}" "$remote" "mkdir -p '$remote_dir' '$remote_source'"

echo "Uploading archive with scp..."
scp "${ssh_args[@]}" "$archive_path" "$remote:$remote_archive"

echo "Extracting archive on remote server..."
ssh "${ssh_args[@]}" "$remote" "tar -xzf '$remote_archive' -C '$remote_source' --strip-components=1"

cat <<EOF

Uploaded knowledge files to:
  $remote:$remote_source

To package those files on the server, run:
  ${connect_parts[*]}
  cd '$APP_DIR'
  set -a; . /etc/kb/production.env; set +a
  REAL_CONTENT_SOURCE_DIR='$remote_source' make real-content-package

Then restore the produced artifact into the active production stack as described in ops/deploy.md.
EOF
