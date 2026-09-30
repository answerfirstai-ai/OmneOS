#!/usr/bin/env bash
# Headless boot test for an OMNE ISO. Exit 0 only when every check passes,
# including the OMNE desktop. This script does not open a physical disk.
set -euo pipefail

image=""
dry_run=0
timeout_seconds=180
work=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --iso)
      image="${2:-}"
      shift 2
      ;;
    --timeout)
      timeout_seconds="${2:-}"
      shift 2
      ;;
    --work)
      work="${2:-}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
    *)
      image="$1"
      shift
      ;;
  esac
done

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

refuse_path() {
  local candidate="$1"
  local resolved
  resolved="$(realpath -m "${candidate}")"
  case "${resolved}" in
    /dev | /dev/* | /boot | /boot/* | /efi | /efi/*)
      echo "refusing to use ${candidate}; no virtual machine was started" >&2
      exit 2
      ;;
  esac
  if [[ -b "${resolved}" || -b "${candidate}" ]]; then
    echo "refusing to use block device ${candidate}; no virtual machine was started" >&2
    exit 2
  fi
}

if [[ -n "${image}" ]]; then
  refuse_path "${image}"
fi
if [[ -n "${work}" ]]; then
  refuse_path "${work}"
fi

echo "firmware: UEFI"
echo "bootloader: systemd-boot"
echo "arch: x86-64"
echo "gpu: virtio-vga"
echo "network: virtio-net"
echo "input: usb-keyboard usb-tablet"
echo "audio: ich9-hda"
echo "serial: file"
echo "snapshot: available"
echo "desktop: not started"
echo "checks: iso-boots kernel systemd network filesystem omne-service core-health ipc graphical-session wayland omne-shell applications agents models recovery reboot shutdown"
echo "dependencies: omne-service -> core-health -> ipc -> graphical-session -> wayland -> omne-shell -> applications -> agents -> models -> recovery"
echo "blocked: a failed dependency marks later checks BLOCKED"
echo "OS-ready requires the OMNE desktop"

if [[ -z "${image}" || ! -f "${image}" ]]; then
  echo "image not found: ${image:-}; no virtual machine was started" >&2
  exit 2
fi

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no virtual machine was started"
  exit 0
fi

if ! command -v qemu-system-x86_64 >/dev/null 2>&1 || ! command -v qemu-img >/dev/null 2>&1; then
  echo "qemu is not installed; no virtual machine was started" >&2
  exit 2
fi

if [[ -z "${work}" ]]; then
  work="$(mktemp -d /var/tmp/omne-vm-test.XXXXXX)"
fi
mkdir -p "${work}"
refuse_path "${work}"
image="$(realpath -m "${image}")"
serial="${work}/serial.log"
monitor="${work}/monitor.sock"
disk="${work}/data.qcow2"
qemu_pid=""

cleanup() {
  local status=$?
  if [[ -n "${qemu_pid}" ]] && kill -0 "${qemu_pid}" 2>/dev/null; then
    kill "${qemu_pid}" 2>/dev/null || true
    wait "${qemu_pid}" 2>/dev/null || true
  fi
  exit "${status}"
}
trap cleanup EXIT

qemu-img create -f qcow2 "${disk}" 1G >/dev/null
qemu-img snapshot -c baseline "${disk}"
disk_hash="$(sha256sum "${disk}" | awk '{print $1}')"
iso_hash="$(sha256sum "${image}" | awk '{print $1}')"
: > "${serial}"

bash "${script_root}/scripts/linux/vm-boot.sh" \
  --run \
  --headless \
  --snapshot \
  --work "${work}" \
  --serial "${serial}" \
  --monitor "${monitor}" \
  --disk "${disk}" \
  "${image}" >"${work}/qemu.out" 2>&1 &
qemu_pid=$!

clean_log() {
  if [[ ! -s "${serial}" ]]; then
    return
  fi
  sed -E $'s/\x1b\\[[0-9;]*[[:alpha:]]//g' "${serial}" | tr -d '\r' > "${work}/serial.clean"
}

wait_for() {
  local needle="$1"
  local seconds="$2"
  local deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    clean_log
    if [[ -f "${work}/serial.clean" ]] && grep -q "${needle}" "${work}/serial.clean"; then
      return 0
    fi
    if ! kill -0 "${qemu_pid}" 2>/dev/null; then
      return 1
    fi
    sleep 2
  done
  return 1
}

monitor_cmd() {
  python3 - "${monitor}" "$1" <<'PY'
import socket
import sys

path, command = sys.argv[1], sys.argv[2]
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(5)
sock.connect(path)
try:
    sock.recv(4096)
except TimeoutError:
    pass
sock.sendall((command + "\n").encode())
# Read until the monitor prompt so the command is not cancelled by a short socket.
buffer = b""
while b"(qemu)" not in buffer:
    try:
        chunk = sock.recv(4096)
    except TimeoutError:
        break
    if not chunk:
        break
    buffer += chunk
sock.close()
if b"(qemu)" not in buffer:
    raise SystemExit(1)
PY
}

boot_ok=0
if wait_for "Reached target multi-user.target" "${timeout_seconds}"; then
  boot_ok=1
  # The checklist retries core health. Score it before the guest is rebooted.
  if ! wait_for "OMNE READY" 90; then
    wait_for "OMNE NOT READY" 60 || true
  fi
  # The session and the doctor start after multi-user.target.
  wait_for "labwc running" 90 || true
  wait_for "OMNE desktop ready" 90 || true
  wait_for "SYSTEM STATUS:" 180 || true
fi
clean_log
log="${work}/serial.clean"
touch "${log}"

linux_before=0
multi_before=0
if [[ -f "${log}" ]]; then
  linux_before="$(grep -c "Linux version" "${log}" || true)"
  multi_before="$(grep -c "Reached target multi-user.target" "${log}" || true)"
fi
reboot_ok=0
if [[ "${boot_ok}" -eq 1 ]] && kill -0 "${qemu_pid}" 2>/dev/null; then
  if [[ -S "${work}/reboot.sock" ]]; then
    python3 - "${work}/reboot.sock" <<'PY' || true
import socket
import sys
import time

path = sys.argv[1]
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect(path)
        sock.sendall(b"reboot\n")
    except OSError:
        pass
    finally:
        sock.close()
    time.sleep(0.4)
PY
  fi
  monitor_cmd "sendkey ctrl-alt-delete 100" || true
  if wait_for "Reached target reboot.target" 120; then
    reboot_ok=1
  fi
  deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    clean_log
    linux_now="$(grep -c "Linux version" "${log}" || true)"
    multi_now="$(grep -c "Reached target multi-user.target" "${log}" || true)"
    if [[ "${linux_now}" -gt "${linux_before}" && "${multi_now}" -gt "${multi_before}" ]]; then
      reboot_ok=1
      break
    fi
    if ! kill -0 "${qemu_pid}" 2>/dev/null; then
      break
    fi
    sleep 2
  done
fi
clean_log

shutdown_ok=0
shutdown_before=0
if [[ -f "${log}" ]]; then
  shutdown_before="$(grep -c "Reached target poweroff.target" "${log}" || true)"
fi
if kill -0 "${qemu_pid}" 2>/dev/null; then
  sleep 2
  deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if ! kill -0 "${qemu_pid}" 2>/dev/null; then
      break
    fi
    monitor_cmd "system_powerdown" || true
    sleep 5
    clean_log
    shutdown_now="$(grep -c "Reached target poweroff.target" "${log}" || true)"
    if [[ "${shutdown_now}" -gt "${shutdown_before}" ]] && ! kill -0 "${qemu_pid}" 2>/dev/null; then
      shutdown_ok=1
      break
    fi
  done
fi
clean_log
shutdown_now="$(grep -c "Reached target poweroff.target" "${log}" || true)"
if [[ "${shutdown_now}" -gt "${shutdown_before}" ]] && ! kill -0 "${qemu_pid}" 2>/dev/null; then
  shutdown_ok=1
fi
later_disk="$(sha256sum "${disk}" | awk '{print $1}')"
later_iso="$(sha256sum "${image}" | awk '{print $1}')"
snapshot_ok=0
if [[ "${later_disk}" == "${disk_hash}" && "${later_iso}" == "${iso_hash}" ]]; then
  snapshot_ok=1
  echo "snapshot: backing disk unchanged"
else
  echo "snapshot: backing disk changed" >&2
fi
if qemu-img snapshot -l "${disk}" | grep -q baseline; then
  echo "snapshot: baseline present"
else
  echo "snapshot: baseline missing" >&2
  snapshot_ok=0
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
artifact="${script_root}/artifacts/vm-test/${run_id}"
score_args=(
  --log "${log}"
  --dest "${artifact}"
  --run-id "${run_id}"
  --elapsed-ms "$((SECONDS * 1000))"
)
if [[ "${snapshot_ok}" -eq 1 ]]; then
  score_args+=(--snapshot-ok)
fi
if ! kill -0 "${qemu_pid}" 2>/dev/null; then
  score_args+=(--guest-exited)
fi
echo "log: ${work}/serial.clean"
python3 "${script_root}/scripts/linux/vm-score.py" "${score_args[@]}"
