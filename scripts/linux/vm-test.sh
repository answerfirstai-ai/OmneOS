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
echo "checks: iso-boots kernel systemd omne-service core-health graphical-session omne-shell network filesystem applications agents models reboot shutdown recovery"
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
results="${work}/results.txt"
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
  sleep 3
fi
clean_log
log="${work}/serial.clean"
touch "${log}"

record() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${results}"
  echo "$2 $1: $3"
}
: > "${results}"

if grep -q "Linux version" "${log}" && grep -q "root=LABEL=OMNE" "${log}"; then
  record iso-boots pass "kernel command line mounted the OMNE ISO"
else
  record iso-boots fail "the serial log did not show an OMNE kernel command line"
fi
if grep -q "Linux version" "${log}"; then
  record kernel pass "Linux version was printed"
else
  record kernel fail "Linux version was not printed"
fi
if grep -q "Reached target multi-user.target" "${log}"; then
  record systemd pass "multi-user.target was reached"
else
  record systemd fail "multi-user.target was not reached"
fi
if grep -q "Started omne-core.service" "${log}" && grep -q "Reached target omne.target" "${log}"; then
  record omne-service pass "omne.target started OMNE Core"
else
  record omne-service fail "omne.target did not start"
fi
if grep -q "OMNE READY" "${log}"; then
  record core-health pass "the boot checklist reported OMNE READY"
else
  record core-health fail "the boot checklist did not report a healthy core"
fi
if grep -q "labwc" "${log}" || grep -q "Reached target graphical.target" "${log}"; then
  record graphical-session pass "a graphical session was recorded"
else
  record graphical-session fail "labwc and graphical.target were not started"
fi
if grep -q "labwc" "${log}" && grep -q "OMNE desktop ready" "${log}"; then
  record omne-shell pass "the OMNE desktop was shown"
else
  record omne-shell fail "the shell service started without a visible OMNE desktop"
fi
if grep -q "Started systemd-networkd.service" "${log}" \
  && grep -q "Reached target network.target" "${log}" \
  && grep -q "virtio_net" "${log}"; then
  record network pass "systemd-networkd reached network.target on virtio-net"
else
  record network fail "the virtio network did not reach network.target"
fi
if grep -q "root=LABEL=OMNE" "${log}" && grep -q "Reached target local-fs.target" "${log}"; then
  record filesystem pass "the ISO root and local filesystems mounted"
else
  record filesystem fail "the root filesystem did not finish mounting"
fi
if grep -q "application launched" "${log}"; then
  record applications pass "an application launch was recorded"
else
  record applications fail "no application launch was observed"
fi
if grep -q "agent task completed" "${log}"; then
  record agents pass "a safe agent task was recorded"
else
  record agents fail "no safe agent task was observed"
fi
if grep -q "model runtime ready" "${log}"; then
  record models pass "the model runtime reported ready"
else
  record models fail "the model runtime did not report ready"
fi

linux_before=0
multi_before=0
if [[ -f "${log}" ]]; then
  linux_before="$(grep -c "Linux version" "${log}" || true)"
  multi_before="$(grep -c "Reached target multi-user.target" "${log}" || true)"
fi
reboot_ok=0
if [[ "${boot_ok}" -eq 1 ]] && kill -0 "${qemu_pid}" 2>/dev/null; then
  monitor_cmd "sendkey ctrl-alt-delete" || true
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
if [[ "${reboot_ok}" -eq 1 ]]; then
  record reboot pass "systemd reached reboot.target and the guest restarted"
else
  record reboot fail "the guest did not reboot"
fi

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
if [[ "${shutdown_ok}" -eq 1 ]]; then
  record shutdown pass "systemd reached poweroff.target and QEMU exited"
else
  record shutdown fail "the guest did not power off"
fi
if grep -E -q "SAFE_MODE|recovery state RECOVERY" "${log}"; then
  record recovery pass "a recovery state was recorded"
else
  record recovery fail "recovery mode was not observed; the live journal is volatile and no recovery command ran"
fi

later_disk="$(sha256sum "${disk}" | awk '{print $1}')"
later_iso="$(sha256sum "${image}" | awk '{print $1}')"
if [[ "${later_disk}" == "${disk_hash}" && "${later_iso}" == "${iso_hash}" ]]; then
  echo "snapshot: backing disk unchanged"
else
  echo "snapshot: backing disk changed" >&2
  record snapshot fail "a virtual disk or the ISO changed during the run"
fi
if qemu-img snapshot -l "${disk}" | grep -q baseline; then
  echo "snapshot: baseline present"
else
  echo "snapshot: baseline missing" >&2
fi

os_ready=yes
while IFS="$(printf '\t')" read -r name status detail; do
  if [[ "${status}" != "pass" ]]; then
    os_ready=no
  fi
done < "${results}"
if [[ "${os_ready}" == "yes" ]] \
  && grep -q $'^graphical-session\tpass\t' "${results}" \
  && grep -q $'^omne-shell\tpass\t' "${results}"; then
  echo "OS-ready: yes"
  exit 0
fi
echo "OS-ready: no"
echo "log: ${work}/serial.clean"
exit 2
