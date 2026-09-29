#!/usr/bin/env bash
# Build a UEFI disk: systemd-boot, the Ubuntu kernel, initramfs, systemd, OMNE.
# The firmware is the machine's UEFI. This script does not write an ISO or a desktop.
set -euo pipefail

rootfs=""
dest=""
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rootfs)
      rootfs="${2:-}"
      shift 2
      ;;
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

script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -n "${dest}" ]]; then
  case "${dest}" in
    /boot | /boot/*)
      echo "refusing to write a disk at ${dest}" >&2
      exit 2
      ;;
  esac
fi

echo "firmware: UEFI"
echo "bootloader: systemd-boot"
echo "kernel: linux-image-generic"
echo "initramfs: initramfs-tools"
echo "init: systemd"
echo "default target: multi-user.target"
echo "desktop: not installed"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no disk was written"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "not running as root; no disk was written" >&2
  exit 2
fi
if [[ -z "${rootfs}" || ! -d "${rootfs}/etc" ]]; then
  echo "rootfs is required; no disk was written" >&2
  exit 2
fi
if [[ -z "${dest}" ]]; then
  echo "dest is required; no disk was written" >&2
  exit 2
fi
if [[ -e "${dest}" ]]; then
  echo "dest already exists; no disk was written" >&2
  exit 2
fi
for tool in losetup partx mkfs.vfat mkfs.ext4 blkid; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "${tool} is missing; no disk was written" >&2
    exit 2
  fi
done
if ! command -v sgdisk >/dev/null 2>&1 && ! command -v parted >/dev/null 2>&1; then
  echo "sgdisk or parted is missing; no disk was written" >&2
  exit 2
fi

loop=""
work=""
mounts=()
cleanup() {
  local status=$?
  local point
  for ((index = ${#mounts[@]} - 1; index >= 0; index--)); do
    point="${mounts[index]}"
    umount "${point}" 2>/dev/null || umount -l "${point}" 2>/dev/null || true
  done
  if [[ -n "${loop}" ]]; then
    losetup -d "${loop}" 2>/dev/null || true
  fi
  if [[ -n "${work}" ]]; then
    rm -rf "${work}"
  fi
  if [[ "${status}" -ne 0 && -n "${dest}" && -f "${dest}" ]]; then
    rm -f "${dest}"
  fi
  exit "${status}"
}
trap cleanup EXIT

remember() {
  mounts+=("$1")
}

truncate -s 4G "${dest}"
if command -v sgdisk >/dev/null 2>&1; then
  sgdisk -o "${dest}" >/dev/null
  sgdisk -n 1:2048:+256M -t 1:ef00 -c 1:ESP "${dest}" >/dev/null
  sgdisk -n 2:0:0 -t 2:8300 -c 2:root "${dest}" >/dev/null
else
  parted -s "${dest}" mklabel gpt
  parted -s "${dest}" mkpart ESP fat32 1MiB 257MiB
  parted -s "${dest}" set 1 esp on
  parted -s "${dest}" mkpart root ext4 257MiB 100%
fi

loop="$(losetup --find --show "${dest}")"
partx -d "${loop}" >/dev/null 2>&1 || true
partx -a "${loop}" >/dev/null 2>&1 || true
for _ in 1 2 3 4 5; do
  if [[ -b "${loop}p1" && -b "${loop}p2" ]]; then
    break
  fi
  sleep 0.2
done
if [[ ! -b "${loop}p1" || ! -b "${loop}p2" ]]; then
  echo "disk partitions were not created; no disk was written" >&2
  exit 2
fi

mkfs.vfat -F 32 -n ESP "${loop}p1" >/dev/null
mkfs.ext4 -L omne -F "${loop}p2" >/dev/null
root_uuid="$(blkid -s UUID -o value "${loop}p2")"
esp_uuid="$(blkid -s UUID -o value "${loop}p1")"
if [[ -z "${root_uuid}" || -z "${esp_uuid}" ]]; then
  echo "filesystem UUID is missing; no disk was written" >&2
  exit 2
fi

work="$(mktemp -d)"
mkdir -p "${work}/root"
mount "${loop}p2" "${work}/root"
remember "${work}/root"
mkdir -p "${work}/root/proc" "${work}/root/sys" "${work}/root/dev" "${work}/root/run" \
  "${work}/root/tmp" "${work}/root/boot/efi"
chmod 1777 "${work}/root/tmp"
tar -C "${rootfs}" \
  --exclude=./proc --exclude=./sys --exclude=./dev --exclude=./run --exclude=./tmp \
  -cf - . | tar -C "${work}/root" -xf -

bash "${script_root}/scripts/linux/install-kernel.sh" --rootfs "${work}/root"

cat > "${work}/root/etc/fstab" <<EOF
UUID=${root_uuid} / ext4 defaults 0 1
UUID=${esp_uuid} /boot/efi vfat umask=0077 0 2
EOF
ln -sfn /usr/lib/systemd/system/multi-user.target "${work}/root/etc/systemd/system/default.target"
mkdir -p \
  "${work}/root/etc/systemd/system/multi-user.target.wants" \
  "${work}/root/etc/systemd/network"
ln -sfn /dev/null "${work}/root/etc/systemd/system/getty@tty1.service"
ln -sfn /dev/null "${work}/root/etc/systemd/system/serial-getty@ttyS0.service"
if [[ -e "${work}/root/usr/lib/systemd/system/systemd-networkd.service" ]]; then
  ln -sfn /usr/lib/systemd/system/systemd-networkd.service \
    "${work}/root/etc/systemd/system/multi-user.target.wants/systemd-networkd.service"
fi
cat > "${work}/root/etc/systemd/network/20-omne-dhcp.network" <<'EOF'
[Match]
Name=en* eth*

[Network]
DHCP=yes
EOF

for excluded in ubuntu-desktop gdm3 lightdm plymouth; do
  status="$(chroot "${work}/root" dpkg-query -W -f='${Status}' "${excluded}" 2>/dev/null || true)"
  if [[ "${status}" == "install ok installed" ]]; then
    echo "refusing disk: ${excluded} is installed" >&2
    exit 2
  fi
done

mount --bind /proc "${work}/root/proc"
remember "${work}/root/proc"
mount --bind /sys "${work}/root/sys"
remember "${work}/root/sys"
mount --bind /dev "${work}/root/dev"
remember "${work}/root/dev"
if [[ -d /dev/pts ]]; then
  mount --bind /dev/pts "${work}/root/dev/pts"
  remember "${work}/root/dev/pts"
fi
resolv_link=""
if [[ -L "${work}/root/etc/resolv.conf" ]]; then
  resolv_link="$(readlink "${work}/root/etc/resolv.conf")"
  rm -f "${work}/root/etc/resolv.conf"
  cp /etc/resolv.conf "${work}/root/etc/resolv.conf"
fi
printf '%s\n' '#!/bin/sh' 'exit 101' > "${work}/root/usr/sbin/policy-rc.d"
chmod 755 "${work}/root/usr/sbin/policy-rc.d"
# systemd-boot-efi is published in Ubuntu universe, not main.
if [[ -f "${work}/root/etc/apt/sources.list" ]]; then
  sed -i -E '/^deb / { /universe/! s/$/ universe/ }' "${work}/root/etc/apt/sources.list"
fi
chroot "${work}/root" apt-get update
chroot "${work}/root" env DEBIAN_FRONTEND=noninteractive \
  apt-get install -y --no-install-recommends systemd-sysv systemd-boot-efi
rm -f "${work}/root/usr/sbin/policy-rc.d"
if [[ -n "${resolv_link}" ]]; then
  rm -f "${work}/root/etc/resolv.conf"
  ln -s "${resolv_link}" "${work}/root/etc/resolv.conf"
fi
chroot "${work}/root" update-initramfs -u

kernel="$(find "${work}/root/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort | tail -n 1)"
initrd="$(find "${work}/root/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort | tail -n 1)"
efi_source="${work}/root/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
if [[ -z "${kernel}" || -z "${initrd}" || ! -f "${efi_source}" ]]; then
  echo "kernel, initramfs, or systemd-boot is missing; no disk was written" >&2
  exit 2
fi

mkdir -p "${work}/esp/EFI/BOOT" "${work}/esp/EFI/systemd" "${work}/esp/loader/entries" "${work}/esp/omne"
cp "${efi_source}" "${work}/esp/EFI/BOOT/BOOTX64.EFI"
cp "${efi_source}" "${work}/esp/EFI/systemd/systemd-bootx64.efi"
cp "${kernel}" "${work}/esp/omne/vmlinuz"
cp "${initrd}" "${work}/esp/omne/initrd.img"
cat > "${work}/esp/loader/loader.conf" <<'EOF'
default omne.conf
timeout 0
editor no
EOF
cat > "${work}/esp/loader/entries/omne.conf" <<EOF
title OMNE
linux /omne/vmlinuz
initrd /omne/initrd.img
options root=UUID=${root_uuid} rw rootwait quiet loglevel=3 systemd.show_status=false rd.systemd.show_status=false console=tty1 console=ttyS0 consoleblank=0 systemd.unit=multi-user.target
EOF
if mount -t vfat "${loop}p1" "${work}/root/boot/efi" 2>/dev/null; then
  remember "${work}/root/boot/efi"
  cp -a "${work}/esp/." "${work}/root/boot/efi/"
else
  # Some build kernels cannot mount vfat. mtools writes the same tree.
  if ! command -v mcopy >/dev/null 2>&1 || ! command -v mmd >/dev/null 2>&1; then
    echo "vfat cannot be mounted and mtools is missing; no disk was written" >&2
    exit 2
  fi
  export MTOOLS_SKIP_CHECK=1
  mmd -i "${loop}p1" ::EFI ::EFI/BOOT ::EFI/systemd ::loader ::loader/entries ::omne
  mcopy -i "${loop}p1" -s "${work}/esp/EFI/BOOT/BOOTX64.EFI" ::EFI/BOOT/BOOTX64.EFI
  mcopy -i "${loop}p1" -s "${work}/esp/EFI/systemd/systemd-bootx64.efi" ::EFI/systemd/systemd-bootx64.efi
  mcopy -i "${loop}p1" -s "${work}/esp/omne/vmlinuz" ::omne/vmlinuz
  mcopy -i "${loop}p1" -s "${work}/esp/omne/initrd.img" ::omne/initrd.img
  mcopy -i "${loop}p1" -s "${work}/esp/loader/loader.conf" ::loader/loader.conf
  mcopy -i "${loop}p1" -s "${work}/esp/loader/entries/omne.conf" ::loader/entries/omne.conf
fi

echo "disk written to ${dest}"
echo "UEFI systemd-boot kernel initramfs systemd OMNE"
echo "no desktop was installed"
