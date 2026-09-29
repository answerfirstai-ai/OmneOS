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
echo "prerequisite tools are present, but this revision does not write an ISO; no image was built" >&2
echo "UEFI boot is a disk image from scripts/linux/build-disk.sh, using the Ubuntu kernel" >&2
exit 2
