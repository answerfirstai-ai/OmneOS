#!/usr/bin/env bash
# Install Ubuntu's kernel and its initramfs into an OMNE rootfs.
# This script does not compile a kernel, install a bootloader, or install a desktop.
set -euo pipefail

rootfs=""
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rootfs)
      rootfs="${2:-}"
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

echo "kernel package: linux-image-generic"
echo "initramfs: initramfs-tools"
echo "bootloader: not installed"
echo "desktop: not installed"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no kernel was installed"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "not running as root; no kernel was installed" >&2
  exit 2
fi
if [[ -z "${rootfs}" || ! -d "${rootfs}/etc/apt" ]]; then
  echo "rootfs is required; no kernel was installed" >&2
  exit 2
fi

mounted=()
cleanup() {
  local status=$?
  local point
  for point in "${mounted[@]:-}"; do
    umount "${point}" 2>/dev/null || umount -l "${point}" 2>/dev/null || true
  done
  exit "${status}"
}
trap cleanup EXIT

mount_bind() {
  local source="$1"
  local point="$2"
  mkdir -p "${point}"
  if mountpoint -q "${point}"; then
    return
  fi
  mount --bind "${source}" "${point}"
  mounted+=("${point}")
}

mount_bind /proc "${rootfs}/proc"
mount_bind /sys "${rootfs}/sys"
mount_bind /dev "${rootfs}/dev"
if [[ -d /dev/pts ]]; then
  mount_bind /dev/pts "${rootfs}/dev/pts"
fi

resolv_link=""
if [[ -L "${rootfs}/etc/resolv.conf" ]]; then
  resolv_link="$(readlink "${rootfs}/etc/resolv.conf")"
  rm -f "${rootfs}/etc/resolv.conf"
  cp /etc/resolv.conf "${rootfs}/etc/resolv.conf"
fi

mkdir -p "${rootfs}/tmp"
chmod 1777 "${rootfs}/tmp"
printf '%s\n' '#!/bin/sh' 'exit 101' > "${rootfs}/usr/sbin/policy-rc.d"
chmod 755 "${rootfs}/usr/sbin/policy-rc.d"
chroot "${rootfs}" apt-get update
chroot "${rootfs}" env DEBIAN_FRONTEND=noninteractive \
  apt-get install -y --no-install-recommends linux-image-generic initramfs-tools
rm -f "${rootfs}/usr/sbin/policy-rc.d"
if [[ -n "${resolv_link}" ]]; then
  rm -f "${rootfs}/etc/resolv.conf"
  ln -s "${resolv_link}" "${rootfs}/etc/resolv.conf"
fi

for excluded in ubuntu-desktop gdm3 lightdm plymouth; do
  status="$(chroot "${rootfs}" dpkg-query -W -f='${Status}' "${excluded}" 2>/dev/null || true)"
  if [[ "${status}" == "install ok installed" ]]; then
    echo "refusing kernel install: ${excluded} is installed" >&2
    exit 2
  fi
done
if ! compgen -G "${rootfs}/boot/vmlinuz-"* >/dev/null; then
  echo "kernel image is missing after install" >&2
  exit 2
fi
if ! compgen -G "${rootfs}/boot/initrd.img-"* >/dev/null; then
  echo "initramfs is missing after install" >&2
  exit 2
fi

echo "kernel installed in ${rootfs}"
echo "no bootloader and no desktop were installed"
