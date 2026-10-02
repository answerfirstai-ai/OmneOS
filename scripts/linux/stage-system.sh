#!/usr/bin/env bash
# Materialize the OMNE system tree on top of an Ubuntu or Debian filesystem.
# This script does not install a kernel or a bootloader.
set -euo pipefail

dest=""
package="all"
shell_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    --package)
      package="${2:-}"
      shift 2
      ;;
    --shell-dir)
      shell_dir="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${dest}" ]]; then
  echo "dest is required" >&2
  exit 2
fi

case "${dest}" in
  /boot | /boot/*)
    echo "refusing to stage into ${dest}" >&2
    exit 2
    ;;
esac

case "${package}" in
  all | core | shell | system) ;;
  *)
    echo "unknown package: ${package}" >&2
    exit 2
    ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "${root}/system/linux/base"

if [[ -z "${shell_dir}" ]]; then
  shell_dir="${root}/shell"
fi

want_core=0
want_shell=0
want_system=0
case "${package}" in
  all)
    want_core=1
    want_shell=1
    want_system=1
    ;;
  core) want_core=1 ;;
  shell) want_shell=1 ;;
  system) want_system=1 ;;
esac

if [[ "${want_shell}" -eq 1 && ! -f "${shell_dir}/dist/main.js" ]]; then
  echo "shell bundle is missing; run npm run build" >&2
  exit 2
fi

mkdir -p "${dest}"
dest="$(cd "${dest}" && pwd)"
if [[ "${dest}" == "${root}" ]]; then
  echo "refusing to stage into the repository root" >&2
  exit 2
fi

if [[ "${want_core}" -eq 1 ]]; then
  mkdir -p \
    "${dest}/etc/omne" \
    "${dest}/etc/systemd/system" \
    "${dest}/usr/bin" \
    "${dest}/usr/lib/omne/agents" \
    "${dest}/usr/lib/omne/models/manifests" \
    "${dest}/usr/lib/sysusers.d" \
    "${dest}/usr/share/doc/omne-core" \
    "${dest}/var/lib/omne/workspace" \
    "${dest}/var/lib/omne/memory"
  cp "${root}/system/linux/OMNE.toml" "${dest}/etc/omne/OMNE.toml"
  cp "${root}/system/linux/omne-core.service" "${dest}/etc/systemd/system/omne-core.service"
  cp "${root}/system/linux/base" "${dest}/usr/lib/omne/base"
  cp "${root}/system/linux/omne.sysusers" "${dest}/usr/lib/sysusers.d/omne.conf"
  cp "${root}/system/linux/OMNE" "${dest}/usr/bin/OMNE"
  chmod 755 "${dest}/usr/bin/OMNE"
  rm -rf "${dest}/usr/lib/omne/agents" "${dest}/usr/lib/omne/models"
  mkdir -p "${dest}/usr/lib/omne/agents" "${dest}/usr/lib/omne/models/manifests"
  cp -a "${root}/agents/." "${dest}/usr/lib/omne/agents/"
  cp -a "${root}/models/manifests/." "${dest}/usr/lib/omne/models/manifests/"
  cp "${root}/LICENSE" "${dest}/usr/share/doc/omne-core/copyright"
fi

if [[ "${want_shell}" -eq 1 ]]; then
  mkdir -p "${dest}/etc/systemd/system" "${dest}/usr/share/doc/omne-shell" "${dest}/usr/share/omne/shell"
  rm -rf "${dest}/usr/share/omne/shell"
  mkdir -p "${dest}/usr/share/omne/shell"
  cp "${shell_dir}/index.html" "${shell_dir}/styles.css" "${dest}/usr/share/omne/shell/"
  cp -a "${shell_dir}/dist" "${dest}/usr/share/omne/shell/dist"
  cp "${root}/system/linux/omne-shell.service" "${dest}/etc/systemd/system/omne-shell.service"
  cp "${root}/LICENSE" "${dest}/usr/share/doc/omne-shell/copyright"
fi

if [[ "${want_system}" -eq 1 ]]; then
  mkdir -p \
    "${dest}/etc/systemd/system" \
    "${dest}/usr/bin" \
    "${dest}/usr/share/doc/omne-system"
  cp "${root}/system/linux/omne.target" "${dest}/etc/systemd/system/omne.target"
  cp "${root}/system/linux/omne-boot.service" "${dest}/etc/systemd/system/omne-boot.service"
  cp "${root}/system/linux/omne-boot" "${dest}/usr/bin/omne-boot"
  chmod 755 "${dest}/usr/bin/omne-boot"
  cp "${root}/system/linux/omne-diag.service" "${dest}/etc/systemd/system/omne-diag.service"
  cp "${root}/system/linux/omne-diag" "${dest}/usr/bin/omne-diag"
  chmod 755 "${dest}/usr/bin/omne-diag"
  cp "${root}/system/linux/omne-session.service" "${dest}/etc/systemd/system/omne-session.service"
  cp "${root}/system/linux/omne-session" "${dest}/usr/bin/omne-session"
  chmod 755 "${dest}/usr/bin/omne-session"
  cp "${root}/system/linux/omne-login.service" "${dest}/etc/systemd/system/omne-login.service"
  cp "${root}/system/linux/omne-login" "${dest}/usr/bin/omne-login"
  chmod 755 "${dest}/usr/bin/omne-login"
  cp "${root}/system/linux/omne-user-session.service" \
    "${dest}/etc/systemd/system/omne-user-session.service"
  cp "${root}/system/linux/omne-user-session" "${dest}/usr/bin/omne-user-session"
  chmod 755 "${dest}/usr/bin/omne-user-session"
  mkdir -p "${dest}/etc/systemd/system/omne-core.service.d" "${dest}/etc/omne"
  cp "${root}/system/linux/omne-core.service.d/user-session.conf" \
    "${dest}/etc/systemd/system/omne-core.service.d/user-session.conf"
  cp "${root}/system/linux/operator.json" "${dest}/etc/omne/operator.json"
  cp "${root}/system/linux/omne-doctor.service" "${dest}/etc/systemd/system/omne-doctor.service"
  cp "${root}/system/linux/omne-prove" "${dest}/usr/bin/omne-prove"
  chmod 755 "${dest}/usr/bin/omne-prove"
  mkdir -p "${dest}/usr/lib/modules-load.d"
  cp "${root}/system/linux/omne.modules" "${dest}/usr/lib/modules-load.d/omne.conf"
  mkdir -p "${dest}/usr/lib/omne/applications"
  cp "${root}/system/linux/omne-hello" "${dest}/usr/lib/omne/applications/omne-hello"
  chmod 755 "${dest}/usr/lib/omne/applications/omne-hello"
  cp "${root}/system/linux/request-reboot" "${dest}/usr/lib/omne/request-reboot"
  chmod 755 "${dest}/usr/lib/omne/request-reboot"
  cp "${root}/system/linux/omne-reboot.socket" "${dest}/etc/systemd/system/omne-reboot.socket"
  cp "${root}/system/linux/omne-reboot@.service" "${dest}/etc/systemd/system/omne-reboot@.service"
  cp "${root}/system/linux/omne-reboot-listen.service" \
    "${dest}/etc/systemd/system/omne-reboot-listen.service"
  cp "${root}/system/linux/omne-reboot-listen" "${dest}/usr/bin/omne-reboot-listen"
  chmod 755 "${dest}/usr/bin/omne-reboot-listen"
  cp "${root}/system/linux/omne-persist.service" "${dest}/etc/systemd/system/omne-persist.service"
  cp "${root}/system/linux/omne-persist" "${dest}/usr/bin/omne-persist"
  chmod 755 "${dest}/usr/bin/omne-persist"
  cp "${root}/system/linux/state.conf" "${dest}/etc/omne/state.conf"
  cp "${root}/LICENSE" "${dest}/usr/share/doc/omne-system/copyright"
fi

if [[ -e "${dest}/boot" ]]; then
  echo "staged tree must not contain /boot" >&2
  exit 2
fi

echo "staged ${package} at ${dest}"
echo "base ${OMNE_BASE_ID} ${OMNE_BASE_VERSION} (${OMNE_BASE_CODENAME})"
echo "no kernel and no bootloader were added"
