#!/usr/bin/env bash
# Boot an OMNE ISO or UEFI disk in QEMU. This does not open a physical disk.
set -euo pipefail

image=""
dry_run=0
run=0
headless=1
serial_path=""
monitor_path=""
disk_path=""
work=""
snapshot=0
memory="2048"
cpus="2"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --run)
      run=1
      shift
      ;;
    --headless)
      headless=1
      shift
      ;;
    --display)
      if [[ "${2:-}" == "none" ]]; then
        headless=1
      elif [[ "${2:-}" == "gtk" ]]; then
        headless=0
      else
        echo "unknown display: ${2:-}" >&2
        exit 2
      fi
      shift 2
      ;;
    --serial)
      serial_path="${2:-}"
      shift 2
      ;;
    --monitor)
      monitor_path="${2:-}"
      shift 2
      ;;
    --disk)
      disk_path="${2:-}"
      shift 2
      ;;
    --work)
      work="${2:-}"
      shift 2
      ;;
    --snapshot)
      snapshot=1
      shift
      ;;
    --memory)
      memory="${2:-}"
      shift 2
      ;;
    --smp)
      cpus="${2:-}"
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

image="${image:-OMNE-OS.img}"

refuse_path() {
  local label="$1"
  local candidate="$2"
  local resolved
  resolved="$(realpath -m "${candidate}")"
  case "${resolved}" in
    /dev | /dev/* | /boot | /boot/* | /efi | /efi/*)
      echo "refusing to use ${label} ${candidate}; no virtual machine was started" >&2
      exit 2
      ;;
  esac
  if [[ -b "${resolved}" || -b "${candidate}" ]]; then
    echo "refusing to use block device ${candidate}; no virtual machine was started" >&2
    exit 2
  fi
}

refuse_path "image" "${image}"
if [[ -n "${disk_path}" ]]; then
  refuse_path "disk" "${disk_path}"
fi
if [[ -n "${work}" ]]; then
  refuse_path "work" "${work}"
fi
if [[ -n "${serial_path}" ]]; then
  refuse_path "serial" "${serial_path}"
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

if [[ ! -f "${image}" ]]; then
  echo "image not found: ${image}; no virtual machine was started" >&2
  exit 2
fi
if [[ -n "${disk_path}" && -e "${disk_path}" && ! -f "${disk_path}" ]]; then
  echo "disk is not a regular file: ${disk_path}; no virtual machine was started" >&2
  exit 2
fi

if [[ "${dry_run}" -eq 1 ]]; then
  echo "desktop: not started"
  echo "dry-run: no virtual machine was started"
  exit 0
fi

echo "desktop: automatic"
echo "boot chain: QEMU -> UEFI -> systemd-boot -> Linux -> systemd -> OMNE services -> graphical session -> OMNE Shell"

qemu_bin="${OMNE_QEMU_BIN:-qemu-system-x86_64}"
qemu_img="${OMNE_QEMU_IMG:-qemu-img}"
if ! command -v "${qemu_bin}" >/dev/null 2>&1; then
  echo "qemu-system-x86_64 is not installed; no virtual machine was started" >&2
  exit 2
fi
if ! command -v "${qemu_img}" >/dev/null 2>&1; then
  echo "qemu-img is not installed; no virtual machine was started" >&2
  exit 2
fi

ovmf="${OMNE_OVMF_CODE:-}"
if [[ -z "${ovmf}" ]]; then
  for candidate in \
    /usr/share/OVMF/OVMF_CODE_4M.fd \
    /usr/share/OVMF/OVMF_CODE.fd \
    /usr/share/ovmf/OVMF.fd
  do
    if [[ -f "${candidate}" ]]; then
      ovmf="${candidate}"
      break
    fi
  done
fi
if [[ -z "${ovmf}" || ! -f "${ovmf}" ]]; then
  echo "OVMF is missing; no virtual machine was started" >&2
  exit 2
fi

vars_template="${OMNE_OVMF_VARS:-}"
if [[ -z "${vars_template}" ]]; then
  for candidate in \
    /usr/share/OVMF/OVMF_VARS_4M.fd \
    /usr/share/OVMF/OVMF_VARS.fd
  do
    if [[ -f "${candidate}" ]]; then
      vars_template="${candidate}"
      break
    fi
  done
fi
if [[ -z "${vars_template}" || ! -f "${vars_template}" ]]; then
  echo "OVMF variable store is missing; no virtual machine was started" >&2
  exit 2
fi

if [[ -z "${work}" ]]; then
  work="$(mktemp -d /var/tmp/omne-vm.XXXXXX)"
fi
mkdir -p "${work}"
refuse_path "work" "${work}"

iso=0
if python3 - "${image}" <<'PY'
import sys

with open(sys.argv[1], "rb") as handle:
    handle.seek(0x8001)
    magic = handle.read(5)
sys.exit(0 if magic == b"CD001" else 1)
PY
then
  iso=1
fi

vars="${work}/ovmf-vars.fd"
cp "${vars_template}" "${vars}"
if [[ -z "${serial_path}" ]]; then
  serial_path="${work}/serial.log"
fi
if [[ -z "${monitor_path}" ]]; then
  monitor_path="${work}/monitor.sock"
fi
rm -f "${monitor_path}"
if [[ -z "${disk_path}" ]]; then
  disk_path="${work}/data.qcow2"
fi
if [[ ! -e "${disk_path}" ]]; then
  "${qemu_img}" create -f qcow2 "${disk_path}" 1G >/dev/null
fi

args=(
  "${qemu_bin}"
  -name omne
  -machine "q35,accel=${OMNE_QEMU_ACCEL:-kvm:tcg}"
  -cpu qemu64
  -m "${memory}"
  -smp "${cpus}"
  -serial "file:${serial_path}"
  -monitor "unix:${monitor_path},server,nowait"
  -drive "if=pflash,format=raw,readonly=on,file=${ovmf}"
  -drive "if=pflash,format=raw,file=${vars}"
  -netdev "user,id=net0"
  -device virtio-net-pci,netdev=net0
  -device virtio-vga
  -device qemu-xhci
  -device usb-kbd
  -device usb-tablet
  -audiodev none,id=snd0
  -device ich9-intel-hda
  -device hda-duplex,audiodev=snd0
)
if [[ "${headless}" -eq 1 ]]; then
  args+=(-display none)
else
  args+=(-display gtk)
fi
if [[ "${snapshot}" -eq 1 ]]; then
  args+=(-snapshot)
fi
if [[ "${iso}" -eq 1 ]]; then
  args+=(
    -cdrom "${image}"
    -drive "if=none,id=disk,format=qcow2,file=${disk_path}"
    -device virtio-blk-pci,drive=disk
  )
else
  args+=(
    -drive "if=none,id=disk,format=raw,file=${image}"
    -device virtio-blk-pci,drive=disk
  )
fi

echo "starting virtual machine"
echo "work: ${work}"
echo "serial: ${serial_path}"
echo "monitor: ${monitor_path}"
exec "${args[@]}"
