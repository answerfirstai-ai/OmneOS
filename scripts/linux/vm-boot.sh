#!/usr/bin/env bash
# Report whether a VM boot can run. This script does not start QEMU.
set -euo pipefail

image="${1:-JARVIS-OS.iso}"
if [[ ! -f "${image}" ]]; then
  echo "image not found: ${image}; no virtual machine was started" >&2
  exit 2
fi
if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "qemu-system-x86_64 is not installed; no virtual machine was started" >&2
  exit 2
fi
echo "refusing to boot ${image}; set up an image build before requesting a virtual machine run" >&2
exit 2
