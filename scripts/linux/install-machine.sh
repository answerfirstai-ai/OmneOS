#!/usr/bin/env bash
# Install OMNE onto a directory root. This script does not format a disk.
set -euo pipefail

dest=""
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${dest}" ]]; then
  echo "dest is required" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
args=(--dest "${dest}" --source "${root}")
if [[ "${dry_run}" -eq 1 ]]; then
  args+=(--dry-run)
fi

cd "${root}"
exec python3 -m omne.install "${args[@]}"
