#!/usr/bin/env bash
# Write a GPT disk image as a regular file: ESP, root, and OMNE-STATE.
# The image is not a loop device, a host disk, or any block device.
set -euo pipefail

export PATH="/usr/sbin:/sbin:${PATH}"

dest=""
esp_dir=""
root_dir=""
state_dir=""
esp_mib=192
root_mib=32
state_mib=64
dry_run=0
root_label="omne"
state_label="OMNE-STATE"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    --esp-dir)
      esp_dir="${2:-}"
      shift 2
      ;;
    --root-dir)
      root_dir="${2:-}"
      shift 2
      ;;
    --state-dir)
      state_dir="${2:-}"
      shift 2
      ;;
    --esp-mib)
      esp_mib="${2:-}"
      shift 2
      ;;
    --root-mib)
      root_mib="${2:-}"
      shift 2
      ;;
    --state-mib)
      state_mib="${2:-}"
      shift 2
      ;;
    --root-label)
      root_label="${2:-}"
      shift 2
      ;;
    --state-label)
      state_label="${2:-}"
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

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

refuse_dest() {
  local candidate="$1"
  local resolved
  resolved="$(realpath -m "${candidate}")"
  case "${resolved}" in
    /boot | /boot/* | /efi | /efi/* | /dev | /dev/*)
      echo "refusing to write a disk at ${candidate}; no disk was written" >&2
      exit 2
      ;;
  esac
  if [[ -b "${resolved}" || -b "${candidate}" ]]; then
    echo "refusing to write a disk to block device ${candidate}; no disk was written" >&2
    exit 2
  fi
  local repo_real
  repo_real="$(realpath -m "${script_root}")"
  case "${resolved}" in
    "${repo_real}" | "${repo_real}"/*)
      echo "refusing to write a disk inside the source tree (${candidate}); no disk was written" >&2
      exit 2
      ;;
  esac
}

if [[ -n "${dest}" ]]; then
  refuse_dest "${dest}"
fi

echo "firmware: UEFI"
echo "bootloader: systemd-boot"
echo "state: ${state_label} mounted at /var/lib/omne"
echo "partitions: ESP root ${state_label}"
echo "host disk: not written"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no disk was written"
  exit 0
fi

if [[ -z "${dest}" ]]; then
  echo "dest is required; no disk was written" >&2
  exit 2
fi
if [[ -z "${esp_dir}" || ! -d "${esp_dir}" ]]; then
  echo "esp directory is required; no disk was written" >&2
  exit 2
fi
dest="$(realpath -m "${dest}")"
refuse_dest "${dest}"
if [[ -e "${dest}" ]]; then
  echo "dest already exists; no disk was written" >&2
  exit 2
fi
for tool in sgdisk mkfs.vfat mkfs.ext4 mcopy mmd dd python3 debugfs; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "${tool} is missing; no disk was written" >&2
    exit 2
  fi
done
case "${state_label}" in
  *[!A-Za-z0-9-]*)
    echo "refusing state label; no disk was written" >&2
    exit 2
    ;;
esac

work=""
cleanup() {
  local status=$?
  if [[ -n "${work}" ]]; then
    rm -rf "${work}"
  fi
  if [[ "${status}" -ne 0 && -n "${dest}" && -f "${dest}" ]]; then
    rm -f "${dest}"
  fi
  exit "${status}"
}
trap cleanup EXIT

work="$(mktemp -d /var/tmp/omne-assemble.XXXXXX)"
esp_bytes=$((esp_mib * 1024 * 1024))
root_bytes=$((root_mib * 1024 * 1024))
state_bytes=$((state_mib * 1024 * 1024))
# 1 MiB in front of the ESP, 1 MiB after the last partition for the backup GPT.
disk_bytes=$((1024 * 1024 + esp_bytes + root_bytes + state_bytes + 1024 * 1024))

truncate -s "${esp_bytes}" "${work}/esp.img"
truncate -s "${root_bytes}" "${work}/root.img"
truncate -s "${state_bytes}" "${work}/state.img"
mkfs.vfat -F 32 -n ESP "${work}/esp.img" >/dev/null
mkfs.ext4 -q -F -L "${root_label}" "${work}/root.img"
mkfs.ext4 -q -F -L "${state_label}" "${work}/state.img"

export MTOOLS_SKIP_CHECK=1
python3 - "${esp_dir}" "${work}/esp.img" <<'PY'
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1])
image = sys.argv[2]
files = sorted(path for path in source.rglob("*") if path.is_file())
directories = []
seen = set()
for path in files:
    relative = path.relative_to(source)
    parent = relative.parent
    parts = parent.parts
    for index in range(1, len(parts) + 1):
        directory = "/".join(parts[:index])
        if directory not in seen:
            seen.add(directory)
            directories.append(directory)
for directory in directories:
    subprocess.run(["mmd", "-i", image, f"::{directory}"], check=False, capture_output=True)
for path in files:
    relative = path.relative_to(source).as_posix()
    subprocess.run(["mcopy", "-i", image, str(path), f"::{relative}"], check=True)
PY

copy_tree() {
  local source="$1"
  local image="$2"
  if [[ -z "${source}" || ! -d "${source}" ]]; then
    return 0
  fi
  python3 - "${source}" "${image}" <<'PY'
import subprocess
import sys
from pathlib import Path

source = Path(sys.argv[1])
image = sys.argv[2]
files = sorted(path for path in source.rglob("*") if path.is_file())
created = set()
commands = []
for path in files:
    relative = path.relative_to(source).as_posix()
    parent = str(Path(relative).parent).replace("\\", "/")
    if parent != ".":
        parts = parent.split("/")
        for index in range(1, len(parts) + 1):
            directory = "/".join(parts[:index])
            if directory not in created:
                created.add(directory)
                commands.append(f"mkdir {directory}")
    commands.append(f"write {path} {relative}")
script = Path(sys.argv[1]).with_name(".debugfs-cmds")
# The command file must not live inside the source tree being copied.
script = Path("/tmp") / f"omne-debugfs-{Path(image).name}.cmds"
script.write_text("\n".join(commands) + "\n", encoding="utf-8")
subprocess.run(["debugfs", "-w", "-f", str(script), image], check=True)
script.unlink(missing_ok=True)
PY
}

copy_tree "${root_dir}" "${work}/root.img"
copy_tree "${state_dir}" "${work}/state.img"

truncate -s "${disk_bytes}" "${dest}"
sgdisk -o "${dest}" >/dev/null
sgdisk -n "1:2048:+${esp_mib}M" -t 1:ef00 -c 1:ESP "${dest}" >/dev/null
sgdisk -n "2:0:+${root_mib}M" -t 2:8300 -c 2:root "${dest}" >/dev/null
sgdisk -n "3:0:+${state_mib}M" -t 3:8300 -c 3:"${state_label}" "${dest}" >/dev/null

python3 - "${dest}" "${work}/esp.img" "${work}/root.img" "${work}/state.img" "${state_label}" <<'PY'
import subprocess
import sys
from pathlib import Path

disk = Path(sys.argv[1])
images = [Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])]
label = sys.argv[5].encode("ascii")

def partition(number: int) -> tuple[int, int]:
    text = subprocess.check_output(["sgdisk", "-i", str(number), str(disk)], text=True)
    start = size = None
    for line in text.splitlines():
        if line.startswith("First sector:"):
            start = int(line.split(":", 1)[1].strip().split()[0])
        elif line.startswith("Partition size:"):
            size = int(line.split(":", 1)[1].strip().split()[0])
    if start is None or size is None:
        raise SystemExit(f"partition {number} is missing")
    return start, size

for number, image in enumerate(images, start=1):
    start, sectors = partition(number)
    if image.stat().st_size > sectors * 512:
        raise SystemExit(f"partition {number} is smaller than its filesystem")
    subprocess.run(
        ["dd", f"if={image}", f"of={disk}", "bs=512", f"seek={start}", "conv=notrunc", "status=none"],
        check=True,
    )

start, _sectors = partition(3)
with disk.open("rb") as handle:
    handle.seek(start * 512 + 1144)
    found = handle.read(16).split(b"\x00", 1)[0]
if found != label:
    raise SystemExit(f"state label is {found!r}, expected {label!r}")
PY

echo "disk written to ${dest}"
echo "state partition: ${state_label}"
echo "no host disk and no block device were written"
