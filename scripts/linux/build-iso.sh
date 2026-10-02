#!/usr/bin/env bash
# Build an x86-64 UEFI ISO of OMNE OS inside a temporary directory.
# The host disk and the host bootloader are not modified.
# Physical installation is not performed.
set -euo pipefail

dest=""
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
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
# shellcheck disable=SC1091
source "${script_root}/system/linux/base"
# shellcheck disable=SC1091
source "${script_root}/system/linux/iso.conf"
# shellcheck disable=SC1091
source "${script_root}/system/linux/state.conf"
if [[ "${OMNE_ISO_STATE_LABEL}" != "${OMNE_STATE_LABEL}" ]]; then
  echo "state label does not match ${OMNE_STATE_LABEL}; no image was built" >&2
  exit 2
fi

supported_path() {
  cat >&2 <<'EOF'
Supported build path: Ubuntu 24.04 x86-64 with root, debootstrap, xorriso, sgdisk, mtools, and e2fsprogs.
  sudo bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso
Privileged container:
  docker run --privileged --rm -v "$PWD":/src -w /src ubuntu:24.04 bash -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y debootstrap xorriso gdisk mtools dosfstools e2fsprogs python3 python3-pip && bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso'
CI: an ubuntu-24.04 runner with sudo. Run the same command from workflow_dispatch. The image is not built on every pull request.
Physical installation is not performed.
EOF
}

refuse_dest() {
  local candidate="$1"
  case "${candidate}" in
    /boot | /boot/* | /efi | /efi/* | /dev | /dev/*)
      echo "refusing to write an ISO at ${candidate}; no image was built" >&2
      exit 2
      ;;
  esac
  if [[ -b "${candidate}" ]]; then
    echo "refusing to write an ISO to block device ${candidate}; no image was built" >&2
    exit 2
  fi
  local repo_real dest_real
  repo_real="$(realpath -m "${script_root}")"
  dest_real="$(realpath -m "${candidate}")"
  case "${dest_real}" in
    "${repo_real}" | "${repo_real}"/*)
      echo "refusing to write an ISO inside the source tree (${candidate}); no image was built" >&2
      exit 2
      ;;
  esac
}

if [[ -n "${dest}" ]]; then
  refuse_dest "${dest}"
fi

detected_system="${OMNE_ISO_UNAME:-$(uname -s)}"
detected_machine="${OMNE_ISO_MACHINE:-$(uname -m)}"
supported_machine=0
if [[ "${detected_machine}" == "x86_64" || "${detected_machine}" == "amd64" ]]; then
  supported_machine=1
fi
if [[ "${detected_system}" != "Linux" || "${supported_machine}" -ne 1 ]]; then
  echo "this environment cannot build an OMNE OS ISO (${detected_system} ${detected_machine}); no image was built" >&2
  supported_path
  exit 2
fi

echo "OMNE Linux base: ${OMNE_BASE_ID} ${OMNE_BASE_VERSION} (${OMNE_BASE_CODENAME})"
echo "kernel: linux-image-generic"
echo "initramfs: initramfs-tools"
echo "bootloader: systemd-boot"
echo "init: systemd"
echo "compositor: labwc"
echo "network: systemd-networkd"
echo "recovery: included"
echo "graphics: labwc installed, not started"
echo "state: ${OMNE_STATE_LABEL} mounted at ${OMNE_STATE_MOUNT}"
echo "volatile /var: kept"
echo "physical installation: not performed"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no ISO was written"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "not running as root; no image was built" >&2
  supported_path
  exit 2
fi

for tool in debootstrap xorriso sgdisk mcopy mmd mkfs.vfat mkfs.ext4 sha256sum python3; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "${tool} is missing; no image was built" >&2
    supported_path
    exit 2
  fi
done
if [[ -z "${dest}" ]]; then
  echo "dest is required; no image was built" >&2
  exit 2
fi
dest="$(realpath -m "${dest}")"
refuse_dest "${dest}"
if [[ -e "${dest}" || -e "${dest}.sha256" || -e "${dest}.json" ]]; then
  echo "dest already exists; no image was built" >&2
  exit 2
fi

version="$(sed -n 's/^version = "\(.*\)"/\1/p' "${script_root}/pyproject.toml" | head -n 1)"
if [[ -z "${version}" ]]; then
  echo "project version is missing; no image was built" >&2
  exit 2
fi

work=""
mounts=()
cleanup() {
  local status=$?
  local index point
  for ((index = ${#mounts[@]} - 1; index >= 0; index--)); do
    point="${mounts[index]}"
    umount "${point}" 2>/dev/null || umount -l "${point}" 2>/dev/null || true
  done
  if [[ -n "${work}" ]]; then
    rm -rf "${work}"
  fi
  if [[ "${status}" -ne 0 && -n "${dest}" ]]; then
    rm -f "${dest}" "${dest}.sha256" "${dest}.json"
  fi
  exit "${status}"
}
trap cleanup EXIT

work="$(mktemp -d /var/tmp/omne-iso.XXXXXX)"
rootfs="${work}/rootfs"

remember() {
  mounts+=("$1")
}

mount_bind() {
  local source="$1"
  local point="$2"
  mkdir -p "${point}"
  if mountpoint -q "${point}"; then
    return
  fi
  mount --bind "${source}" "${point}"
  remember "${point}"
}

unmount_all() {
  local index point
  for ((index = ${#mounts[@]} - 1; index >= 0; index--)); do
    point="${mounts[index]}"
    umount "${point}" 2>/dev/null || umount -l "${point}" 2>/dev/null || true
  done
  mounts=()
}

if [[ ! -f "${script_root}/shell/dist/main.js" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "shell bundle is missing and npm is not available; no image was built" >&2
    exit 2
  fi
  (cd "${script_root}" && npm run build)
fi

echo "building packages"
bash "${script_root}/scripts/linux/build-packages.sh" --dest "${work}/packages"
echo "building rootfs"
bash "${script_root}/scripts/linux/build-base.sh" --dest "${rootfs}" --packages "${work}/packages"
echo "installing kernel"
bash "${script_root}/scripts/linux/install-kernel.sh" --rootfs "${rootfs}"

if [[ -f "${rootfs}/etc/apt/sources.list" ]]; then
  sed -i -E '/^deb / { /universe/! s/$/ universe/ }' "${rootfs}/etc/apt/sources.list"
fi

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
printf '%s\n' '#!/bin/sh' 'exit 101' > "${rootfs}/usr/sbin/policy-rc.d"
chmod 755 "${rootfs}/usr/sbin/policy-rc.d"

echo "installing image packages"
chroot "${rootfs}" apt-get update
chroot "${rootfs}" env DEBIAN_FRONTEND=noninteractive \
  apt-get install -y --no-install-recommends "${OMNE_ISO_PACKAGES[@]}"

for excluded in ubuntu-desktop gdm3 lightdm plymouth grub-pc grub-efi-amd64; do
  status="$(chroot "${rootfs}" dpkg-query -W -f='${Status}' "${excluded}" 2>/dev/null || true)"
  if [[ "${status}" == "install ok installed" ]]; then
    echo "refusing ISO: ${excluded} is installed; no image was built" >&2
    exit 2
  fi
done

mkdir -p "${rootfs}/etc/systemd/system/multi-user.target.wants" "${rootfs}/etc/systemd/network"
ln -sfn /usr/lib/systemd/system/multi-user.target "${rootfs}/etc/systemd/system/default.target"
ln -sfn /dev/null "${rootfs}/etc/systemd/system/getty@tty1.service"
ln -sfn /dev/null "${rootfs}/etc/systemd/system/serial-getty@ttyS0.service"
if [[ -e "${rootfs}/usr/lib/systemd/system/systemd-networkd.service" ]]; then
  ln -sfn /usr/lib/systemd/system/systemd-networkd.service \
    "${rootfs}/etc/systemd/system/multi-user.target.wants/systemd-networkd.service"
fi
if [[ -e "${rootfs}/usr/lib/systemd/system/systemd-networkd-wait-online.service" ]]; then
  mkdir -p "${rootfs}/etc/systemd/system/network-online.target.wants"
  ln -sfn /usr/lib/systemd/system/systemd-networkd-wait-online.service \
    "${rootfs}/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service"
fi
# shellcheck disable=SC1091
source "${script_root}/scripts/linux/enable-units.sh"
enable_omne_units "${rootfs}"
cat > "${rootfs}/etc/systemd/network/20-omne-dhcp.network" <<'EOF'
[Match]
Name=en* eth*

[Network]
DHCP=yes
EOF
mkdir -p "${rootfs}/etc/systemd/journald.conf.d"
cat > "${rootfs}/etc/systemd/journald.conf.d/omne-volatile.conf" <<'EOF'
[Journal]
Storage=volatile
EOF
cat > "${rootfs}/etc/fstab" <<EOF
LABEL=${OMNE_ISO_VOLUME_ID} / iso9660 ro 0 0
tmpfs /tmp tmpfs defaults,mode=1777 0 0
LABEL=${OMNE_STATE_LABEL} ${OMNE_STATE_MOUNT} ext4 nofail,noatime,x-systemd.device-timeout=10s,x-systemd.after=var.mount,x-systemd.before=omne-core.service 0 2
EOF

modules="${rootfs}/etc/initramfs-tools/modules"
touch "${modules}"
for module in iso9660 ext4 overlay cdrom sr_mod; do
  if ! grep -qx "${module}" "${modules}"; then
    printf '%s\n' "${module}" >> "${modules}"
  fi
done
chroot "${rootfs}" update-initramfs -u
chroot "${rootfs}" dpkg-query -W > "${rootfs}/etc/omne/image-packages.txt"
chroot "${rootfs}" apt-get clean
rm -rf "${rootfs}/var/lib/apt/lists/"*
rm -f "${rootfs}/usr/sbin/policy-rc.d"
if [[ -n "${resolv_link}" ]]; then
  rm -f "${rootfs}/etc/resolv.conf"
  ln -s "${resolv_link}" "${rootfs}/etc/resolv.conf"
fi
unmount_all
for point in "${rootfs}/dev/pts" "${rootfs}/dev" "${rootfs}/sys" "${rootfs}/proc"; do
  if mountpoint -q "${point}"; then
    echo "refusing to pack a rootfs that still has ${point} mounted; no image was built" >&2
    exit 2
  fi
done

kernel="$(find "${rootfs}/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort | tail -n 1)"
initrd="$(find "${rootfs}/boot" -maxdepth 1 -type f -name 'initrd.img-*' | sort | tail -n 1)"
efi_source="${rootfs}/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
if [[ -z "${kernel}" || -z "${initrd}" || ! -f "${efi_source}" ]]; then
  echo "kernel, initramfs, or systemd-boot is missing; no image was built" >&2
  exit 2
fi
for required in \
  "${rootfs}/usr/bin/OMNE" \
  "${rootfs}/usr/bin/labwc" \
  "${rootfs}/usr/bin/omne-session" \
  "${rootfs}/usr/bin/omne-login" \
  "${rootfs}/usr/bin/omne-user-session" \
  "${rootfs}/usr/bin/omne-prove" \
  "${rootfs}/etc/omne/operator.json" \
  "${rootfs}/etc/systemd/system/omne-core.service.d/user-session.conf" \
  "${rootfs}/etc/systemd/system/multi-user.target.wants/omne-login.service" \
  "${rootfs}/etc/systemd/system/multi-user.target.wants/omne-session.service" \
  "${rootfs}/etc/systemd/system/local-fs.target.wants/omne-persist.service" \
  "${rootfs}/usr/bin/omne-persist" \
  "${rootfs}/etc/omne/state.conf" \
  "${rootfs}/etc/systemd/system/omne-doctor.service" \
  "${rootfs}/usr/lib/systemd/systemd" \
  "${rootfs}/usr/share/omne/shell/dist/main.js" \
  "${rootfs}/usr/lib/omne/python/omne/recovery/service.py"
do
  if ! image_path_ready "${rootfs}" "${required}"; then
    echo "required image file is missing: ${required}; no image was built" >&2
    exit 2
  fi
done

kernel_version="${kernel##*/vmlinuz-}"
if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
  build_timestamp="$(date -u -d "@${SOURCE_DATE_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)"
else
  build_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
package_pin="$(printf '%s\n' "${OMNE_ISO_PACKAGES[@]}" | sort | paste -sd, -)"
build_id="$(
  {
    printf 'version=%s\n' "${version}"
    printf 'base=%s %s %s\n' "${OMNE_BASE_ID}" "${OMNE_BASE_VERSION}" "${OMNE_BASE_CODENAME}"
    printf 'arch=%s\n' "${OMNE_ISO_ARCH}"
    printf 'kernel=%s\n' "linux-image-generic"
    printf 'initramfs=%s\n' "initramfs-tools"
    printf 'packages=%s\n' "${package_pin}"
    printf 'state=%s %s\n' "${OMNE_STATE_LABEL}" "${OMNE_ISO_STATE_MIB}"
  } | sha256sum | awk '{print substr($1, 1, 16)}'
)"
base_distribution="${OMNE_BASE_ID} ${OMNE_BASE_VERSION} (${OMNE_BASE_CODENAME})"
python3 - "${version}" "${build_id}" "${base_distribution}" "${kernel_version}" \
  "${build_timestamp}" "${OMNE_ISO_ARCH}" "${rootfs}/etc/omne/image.json" <<'PY'
import json
import sys

payload = {
    "name": "OMNE OS",
    "version": sys.argv[1],
    "build_id": sys.argv[2],
    "base_distribution": sys.argv[3],
    "kernel_version": sys.argv[4],
    "build_timestamp": sys.argv[5],
    "arch": sys.argv[6],
    "bootloader": "systemd-boot",
    "compositor": "labwc",
    "physical_install": False,
}
with open(sys.argv[7], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
cp "${script_root}/system/linux/iso.conf" "${rootfs}/etc/omne/iso.conf"

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
options root=LABEL=${OMNE_ISO_VOLUME_ID} rootfstype=iso9660 ro rootwait console=tty1 console=ttyS0 systemd.unit=multi-user.target systemd.volatile=state
EOF

truncate -s "${OMNE_ISO_ESP_MIB}M" "${work}/efiboot.img"
mkfs.vfat -F 32 -n ESP "${work}/efiboot.img" >/dev/null
export MTOOLS_SKIP_CHECK=1
mmd -i "${work}/efiboot.img" ::EFI ::EFI/BOOT ::EFI/systemd ::loader ::loader/entries ::omne
mcopy -i "${work}/efiboot.img" "${work}/esp/EFI/BOOT/BOOTX64.EFI" ::EFI/BOOT/BOOTX64.EFI
mcopy -i "${work}/efiboot.img" "${work}/esp/EFI/systemd/systemd-bootx64.efi" ::EFI/systemd/systemd-bootx64.efi
mcopy -i "${work}/efiboot.img" "${work}/esp/omne/vmlinuz" ::omne/vmlinuz
mcopy -i "${work}/efiboot.img" "${work}/esp/omne/initrd.img" ::omne/initrd.img
mcopy -i "${work}/efiboot.img" "${work}/esp/loader/loader.conf" ::loader/loader.conf
mcopy -i "${work}/efiboot.img" "${work}/esp/loader/entries/omne.conf" ::loader/entries/omne.conf

mkdir -p "${rootfs}/EFI" "${rootfs}/loader" "${rootfs}/omne" "${rootfs}/boot"
cp -a "${work}/esp/EFI/." "${rootfs}/EFI/"
cp -a "${work}/esp/loader/." "${rootfs}/loader/"
cp -a "${work}/esp/omne/." "${rootfs}/omne/"
cp "${work}/efiboot.img" "${rootfs}/boot/efiboot.img"

echo "creating state partition image"
state_image="${work}/omne-state.img"
case "${state_image}" in
  /dev | /dev/*)
    echo "refusing to format a block device; no image was built" >&2
    exit 2
    ;;
esac
if [[ -b "${state_image}" ]]; then
  echo "refusing to format a block device; no image was built" >&2
  exit 2
fi
truncate -s "${OMNE_ISO_STATE_MIB}M" "${state_image}"
mkfs.ext4 -q -F -L "${OMNE_STATE_LABEL}" "${state_image}"

echo "writing ISO"
xorriso -as mkisofs \
  -R -J \
  -V "${OMNE_ISO_VOLUME_ID}" \
  -o "${dest}" \
  -e boot/efiboot.img \
  -no-emul-boot \
  -append_partition 2 0xef "${rootfs}/boot/efiboot.img" \
  -append_partition 3 0x83 "${state_image}" \
  "${rootfs}"
cp "${rootfs}/etc/omne/image.json" "${dest}.json"
sha256sum "${dest}" > "${dest}.sha256"

if ! bash "${script_root}/scripts/linux/validate-iso.sh" --os "${dest}"; then
  echo "ISO validation failed; no image was built" >&2
  exit 2
fi

echo "ISO written to ${dest}"
echo "checksum written to ${dest}.sha256"
echo "validation passed"
echo "no host disk and no host bootloader were modified"
echo "physical installation was not performed"
