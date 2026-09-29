#!/usr/bin/env bash
# Boot an OMNE UEFI disk with QEMU. An ISO is not a bootable OMNE image.
set -euo pipefail

image=""
dry_run=0
run=0

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
echo "firmware: UEFI"
echo "bootloader: systemd-boot"
echo "desktop: not started"

if [[ ! -f "${image}" ]]; then
  echo "image not found: ${image}; no virtual machine was started" >&2
  exit 2
fi

if [[ "${dry_run}" -eq 1 || "${run}" -eq 0 ]]; then
  echo "dry-run: no virtual machine was started"
  exit 0
fi

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "qemu-system-x86_64 is not installed; no virtual machine was started" >&2
  exit 2
fi

ovmf=""
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
if [[ -z "${ovmf}" ]]; then
  echo "OVMF is missing; no virtual machine was started" >&2
  exit 2
fi

vars=""
for candidate in \
  /usr/share/OVMF/OVMF_VARS_4M.fd \
  /usr/share/OVMF/OVMF_VARS.fd
do
  if [[ -f "${candidate}" ]]; then
    vars="$(mktemp)"
    cp "${candidate}" "${vars}"
    break
  fi
done

args=(
  qemu-system-x86_64
  -machine "q35,accel=${OMNE_QEMU_ACCEL:-kvm:tcg}"
  -cpu qemu64
  -m 2048
  -smp 2
  -serial mon:stdio
  -display none
  -vga std
  -drive "if=pflash,format=raw,readonly=on,file=${ovmf}"
)
if [[ -n "${vars}" ]]; then
  args+=(-drive "if=pflash,format=raw,file=${vars}")
fi
args+=(
  -drive "if=none,id=disk,format=raw,file=${image}"
  -device virtio-blk-pci,drive=disk
  -netdev user,id=net0
  -device virtio-net-pci,netdev=net0
)
exec "${args[@]}"
