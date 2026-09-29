#!/usr/bin/env bash
# Install a user-level OMNE Core unit. This script does not change boot configuration.
set -euo pipefail

prefix="${HOME}/.local"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      prefix="${2:-}"
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

if [[ -z "${prefix}" ]]; then
  echo "prefix is required" >&2
  exit 2
fi

case "${prefix}" in
  /boot | /boot/*)
    echo "refusing to install into ${prefix}" >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unit_source="${root}/system/linux/OMNE-core.service"
unit_dir="${prefix}/share/systemd/user"
echo "install prefix ${prefix}"
echo "unit ${unit_dir}/OMNE-core.service"
echo "this installer does not modify the bootloader"
if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no files were written"
  exit 0
fi

mkdir -p "${prefix}/bin" "${unit_dir}"
cp "${unit_source}" "${unit_dir}/OMNE-core.service"
cat > "${prefix}/bin/OMNE-core-health" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if ! command -v OMNE >/dev/null 2>&1; then
  echo "OMNE is not on PATH" >&2
  exit 2
fi
OMNE check
EOF
chmod 755 "${prefix}/bin/OMNE-core-health"
echo "installed user unit; boot configuration was not modified"
