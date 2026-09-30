#!/usr/bin/env bash
# Validate an OMNE OS ISO. The default profile checks structure.
# --os also requires a real kernel, initramfs, checksum, and metadata sidecar.
set -euo pipefail

profile="structure"
iso=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --os)
      profile="os"
      shift
      ;;
    *)
      if [[ -n "${iso}" ]]; then
        echo "unknown argument: $1" >&2
        exit 2
      fi
      iso="$1"
      shift
      ;;
  esac
done

if [[ -z "${iso}" || ! -f "${iso}" ]]; then
  echo "ISO file is missing" >&2
  exit 2
fi
if [[ ! -s "${iso}" ]]; then
  echo "ISO file is empty" >&2
  exit 2
fi

if ! python3 - "${iso}" <<'PY'
import sys

with open(sys.argv[1], "rb") as handle:
    handle.seek(0x8001)
    magic = handle.read(5)
if magic != b"CD001":
    sys.stderr.write("ISO 9660 magic is missing\n")
    sys.exit(1)
PY
then
  exit 2
fi

boot="$(xorriso -indev "${iso}" -report_el_torito plain 2>&1 || true)"
if ! printf '%s\n' "${boot}" | grep -q "El Torito"; then
  echo "El Torito boot record is missing" >&2
  exit 2
fi
if ! printf '%s\n' "${boot}" | grep -q "UEFI"; then
  echo "UEFI boot image is missing" >&2
  exit 2
fi
if ! printf '%s\n' "${boot}" | grep -E -q "Volume id *: 'OMNE'"; then
  echo "volume id is not OMNE" >&2
  exit 2
fi

file_size() {
  local path="$1"
  local report
  report="$(xorriso -indev "${iso}" -find "${path}" -exec report_lba -- 2>/dev/null || true)"
  printf '%s\n' "${report}" | awk -F',' -v wanted="${path}" '
    index($0, "File data lba:") == 1 {
      size = $4
      gsub(/ /, "", size)
      file = $5
      gsub(/^[ ]*'\''|'\''[ ]*$/, "", file)
      if (file == wanted && size ~ /^[0-9]+$/) {
        print size
        exit
      }
    }
  '
}

require_file() {
  local path="$1"
  local minimum="${2:-1}"
  local size
  size="$(file_size "${path}")"
  if [[ -z "${size}" ]]; then
    echo "missing path: ${path}" >&2
    return 1
  fi
  if [[ "${size}" -lt "${minimum}" ]]; then
    if [[ "${minimum}" -le 1 ]]; then
      echo "empty path: ${path}" >&2
    else
      echo "path is too small: ${path}" >&2
    fi
    return 1
  fi
}

require_file /usr/bin/OMNE || exit 2
require_file /usr/bin/labwc || exit 2
if ! require_file /usr/lib/systemd/systemd; then
  require_file /lib/systemd/systemd || exit 2
fi
require_file /etc/systemd/network/20-omne-dhcp.network || exit 2
require_file /etc/omne/image.json || exit 2
require_file /EFI/BOOT/BOOTX64.EFI || exit 2
require_file /omne/vmlinuz || exit 2
require_file /omne/initrd.img || exit 2
require_file /usr/lib/omne/python/omne/recovery/service.py || exit 2

if [[ "${profile}" == "os" ]]; then
  kernel_size="$(file_size /omne/vmlinuz)"
  initrd_size="$(file_size /omne/initrd.img)"
  if [[ -z "${kernel_size}" || "${kernel_size}" -lt 1000000 ]]; then
    echo "kernel image is too small" >&2
    exit 2
  fi
  if [[ -z "${initrd_size}" || "${initrd_size}" -lt 1000000 ]]; then
    echo "initramfs is too small" >&2
    exit 2
  fi
fi

metadata="$(mktemp)"
cleanup() {
  rm -f "${metadata}"
}
trap cleanup EXIT
if ! xorriso -osirrox on -indev "${iso}" -extract /etc/omne/image.json "${metadata}" >/dev/null; then
  echo "image metadata could not be read" >&2
  exit 2
fi
if ! python3 - "${metadata}" "${profile}" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
required = (
    "version",
    "build_id",
    "base_distribution",
    "kernel_version",
    "build_timestamp",
)
missing = [key for key in required if not str(data.get(key, "")).strip()]
if missing:
    sys.stderr.write("image metadata is missing " + ", ".join(missing) + "\n")
    sys.exit(1)
if data.get("physical_install") is not False:
    sys.stderr.write("physical installation is recorded\n")
    sys.exit(1)
stamp = str(data["build_timestamp"])
if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", stamp) is None:
    sys.stderr.write("build timestamp is not UTC\n")
    sys.exit(1)
if sys.argv[2] == "os":
    if re.fullmatch(r"[0-9a-f]{16}", str(data["build_id"])) is None:
        sys.stderr.write("build id is not 16 hex characters\n")
        sys.exit(1)
    if re.match(r"^[0-9]+\.", str(data["kernel_version"])) is None:
        sys.stderr.write("kernel version is not a Linux version\n")
        sys.exit(1)
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(data["version"])) is None:
        sys.stderr.write("OMNE version is missing\n")
        sys.exit(1)
    base = str(data["base_distribution"])
    if "ubuntu" not in base.lower() or "24.04" not in base:
        sys.stderr.write("base distribution is not Ubuntu 24.04\n")
        sys.exit(1)
PY
then
  exit 2
fi

if [[ ! -f "${iso}.sha256" ]]; then
  echo "checksum file is missing" >&2
  exit 2
fi
if ! sha256sum -c "${iso}.sha256" >/dev/null; then
  echo "checksum does not match" >&2
  exit 2
fi

if [[ "${profile}" == "os" ]]; then
  if [[ ! -f "${iso}.json" ]]; then
    echo "build metadata sidecar is missing" >&2
    exit 2
  fi
  if ! cmp -s "${metadata}" "${iso}.json"; then
    echo "build metadata sidecar does not match the ISO" >&2
    exit 2
  fi
fi

echo "validation passed"
