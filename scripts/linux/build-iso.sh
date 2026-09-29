#!/usr/bin/env bash
# Check whether an ISO can be built. This script never writes OMNE-OS.iso.
set -euo pipefail

echo "OMNE OS image build requires root, debootstrap, and xorriso." >&2
if [[ "${EUID}" -ne 0 ]]; then
  echo "not running as root; no image was built" >&2
  exit 2
fi
if ! command -v debootstrap >/dev/null 2>&1 || ! command -v xorriso >/dev/null 2>&1; then
  echo "debootstrap or xorriso is missing; no image was built" >&2
  exit 2
fi
echo "prerequisite tools are present, but this revision does not install a kernel or a bootloader; no image was built" >&2
echo "the development base is Ubuntu 24.04; scripts/linux/build-base.sh writes a rootfs, not an ISO" >&2
exit 2
