#!/usr/bin/env bash
# Build an Ubuntu 24.04 rootfs and install the OMNE packages into it.
# This script does not install a kernel, a bootloader, or an ISO.
set -euo pipefail

dest=""
packages=""
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    --packages)
      packages="${2:-}"
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

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${root}/system/linux/base"

base_packages=(systemd python3)
excluded_packages=(linux-image-generic grub-pc grub-efi-amd64 ubuntu-desktop)

if [[ -n "${dest}" ]]; then
  case "${dest}" in
    /boot | /boot/*)
      echo "refusing to build a rootfs at ${dest}" >&2
      exit 2
      ;;
  esac
fi

echo "OMNE Linux base: ${OMNE_BASE_ID} ${OMNE_BASE_VERSION} (${OMNE_BASE_CODENAME})"
echo "mirror: ${OMNE_BASE_MIRROR}"
echo "variant: minbase"
echo "packages: omne-core omne-shell omne-system"
echo "install: ${base_packages[*]}"
echo "exclude: ${excluded_packages[*]}"
echo "kernel: not installed"
echo "bootloader: not installed"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no rootfs was written"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "not running as root; no rootfs was written" >&2
  exit 2
fi
if ! command -v debootstrap >/dev/null 2>&1; then
  echo "debootstrap is missing; no rootfs was written" >&2
  exit 2
fi
if [[ -z "${dest}" ]]; then
  echo "dest is required; no rootfs was written" >&2
  exit 2
fi
if [[ -z "${packages}" || ! -d "${packages}" ]]; then
  echo "package directory is required; no rootfs was written" >&2
  exit 2
fi

version="$(sed -n 's/^version = "\(.*\)"/\1/p' "${root}/pyproject.toml" | head -n 1)"
for name in omne-core omne-shell omne-system; do
  if [[ ! -f "${packages}/${name}_${version}_all.deb" ]]; then
    echo "missing ${name} package; no rootfs was written" >&2
    exit 2
  fi
done

if [[ -e "${dest}" ]]; then
  echo "dest already exists; no rootfs was written" >&2
  exit 2
fi

mkdir -p "${dest}"
trap 'status=$?; if [[ "${status}" -ne 0 ]]; then rm -rf "${dest}"; fi' EXIT
debootstrap --variant=minbase "${OMNE_BASE_CODENAME}" "${dest}" "${OMNE_BASE_MIRROR}"

cat > "${dest}/etc/apt/sources.list" <<EOF
deb ${OMNE_BASE_MIRROR} ${OMNE_BASE_CODENAME} main
deb ${OMNE_BASE_MIRROR} ${OMNE_BASE_CODENAME}-updates main
deb ${OMNE_BASE_SECURITY_MIRROR} ${OMNE_BASE_CODENAME}-security main
EOF

printf '%s\n' '#!/bin/sh' 'exit 101' > "${dest}/usr/sbin/policy-rc.d"
chmod 755 "${dest}/usr/sbin/policy-rc.d"
chroot "${dest}" apt-get update
chroot "${dest}" env DEBIAN_FRONTEND=noninteractive apt-get install -y "${base_packages[@]}"

for excluded in "${excluded_packages[@]}"; do
  status="$(chroot "${dest}" dpkg-query -W -f='${Status}' "${excluded}" 2>/dev/null || true)"
  if [[ "${status}" == "install ok installed" ]]; then
    echo "refusing rootfs: ${excluded} is installed" >&2
    exit 2
  fi
done
if compgen -G "${dest}/boot/vmlinuz*" >/dev/null || compgen -G "${dest}/lib/modules/*" >/dev/null; then
  echo "refusing rootfs: a kernel was installed" >&2
  exit 2
fi

mkdir -p "${dest}/tmp/omne-packages"
cp "${packages}/omne-core_${version}_all.deb" \
  "${packages}/omne-shell_${version}_all.deb" \
  "${packages}/omne-system_${version}_all.deb" \
  "${dest}/tmp/omne-packages/"
chroot "${dest}" dpkg -i \
  "/tmp/omne-packages/omne-core_${version}_all.deb" \
  "/tmp/omne-packages/omne-shell_${version}_all.deb" \
  "/tmp/omne-packages/omne-system_${version}_all.deb"
rm -rf "${dest}/tmp/omne-packages" "${dest}/usr/sbin/policy-rc.d"

wants="${dest}/etc/systemd/system/multi-user.target.wants"
mkdir -p "${wants}"
ln -sfn /etc/systemd/system/omne.target "${wants}/omne.target"

echo "rootfs written to ${dest}"
echo "no kernel and no bootloader were installed"
