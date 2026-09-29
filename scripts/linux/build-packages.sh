#!/usr/bin/env bash
# Build omne-core, omne-shell, and omne-system Debian packages.
# The packages do not contain a kernel or a bootloader.
set -euo pipefail

dest=""
shell_dir=""
skip_runtime=0
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)
      dest="${2:-}"
      shift 2
      ;;
    --shell-dir)
      shell_dir="${2:-}"
      shift 2
      ;;
    --skip-runtime)
      skip_runtime=1
      shift
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
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "${root}/pyproject.toml" | head -n 1)"
if [[ -z "${version}" ]]; then
  echo "project version is missing" >&2
  exit 2
fi

echo "packages: omne-core omne-shell omne-system"
echo "version: ${version}"
echo "kernel: not included"
echo "bootloader: not included"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no packages were built"
  exit 0
fi

if [[ -z "${dest}" ]]; then
  echo "dest is required; no packages were built" >&2
  exit 2
fi
case "${dest}" in
  /boot | /boot/*)
    echo "refusing to build packages into ${dest}" >&2
    exit 2
    ;;
esac
if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "dpkg-deb is missing; no packages were built" >&2
  exit 2
fi

mkdir -p "${dest}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

stage_args=(--shell-dir "${shell_dir:-${root}/shell}")
bash "${root}/scripts/linux/stage-system.sh" --dest "${work}/core" --package core
bash "${root}/scripts/linux/stage-system.sh" --dest "${work}/shell" --package shell "${stage_args[@]}"
bash "${root}/scripts/linux/stage-system.sh" --dest "${work}/system" --package system

if [[ "${skip_runtime}" -eq 0 ]]; then
  python="python3"
  if [[ -x "${root}/.venv/bin/python" ]]; then
    python="${root}/.venv/bin/python"
  fi
  if ! "${python}" -m pip --version >/dev/null 2>&1; then
    echo "pip is missing; no packages were built" >&2
    exit 2
  fi
  "${python}" -m pip install \
    --disable-pip-version-check \
    --upgrade \
    --target "${work}/core/usr/lib/omne/python" \
    "${root}"
fi

write_control() {
  local name="$1"
  local depends="$2"
  local summary="$3"
  local detail="$4"
  local stage="${work}/${name#omne-}"
  mkdir -p "${stage}/DEBIAN"
  cat > "${stage}/DEBIAN/control" <<EOF
Package: ${name}
Version: ${version}
Section: admin
Priority: optional
Architecture: all
Depends: ${depends}
Maintainer: OMNE OS <omne@localhost>
Description: ${summary}
 ${detail}
EOF
}

write_control \
  omne-core \
  "python3 (>= 3.12)" \
  "OMNE Core system service" \
  "Local OMNE runtime started by systemd. This package does not install a kernel."
cp "${root}/system/linux/omne-core.postinst" "${work}/core/DEBIAN/postinst"
chmod 755 "${work}/core/DEBIAN/postinst"
printf '%s\n' "/etc/omne/OMNE.toml" > "${work}/core/DEBIAN/conffiles"

write_control \
  omne-shell \
  "python3 (>= 3.12), omne-core (= ${version})" \
  "OMNE Shell system service" \
  "Desktop shell served for the local OMNE core. This package does not install a kernel."
write_control \
  omne-system \
  "omne-core (= ${version}), omne-shell (= ${version})" \
  "OMNE system target" \
  "Boots OMNE Core and the OMNE shell from multi-user.target."
cp "${root}/system/linux/omne-system.postinst" "${work}/system/DEBIAN/postinst"
cp "${root}/system/linux/omne-system.prerm" "${work}/system/DEBIAN/prerm"
chmod 755 "${work}/system/DEBIAN/postinst" "${work}/system/DEBIAN/prerm"

# State directories are created for the omne user at install time.
rm -rf "${work}/core/var"

deb_args=()
if dpkg-deb --help 2>/dev/null | grep -q -- '--root-owner-group'; then
  deb_args+=(--root-owner-group)
fi

dpkg-deb "${deb_args[@]}" --build "${work}/core" "${dest}/omne-core_${version}_all.deb"
dpkg-deb "${deb_args[@]}" --build "${work}/shell" "${dest}/omne-shell_${version}_all.deb"
dpkg-deb "${deb_args[@]}" --build "${work}/system" "${dest}/omne-system_${version}_all.deb"

echo "built packages in ${dest}"
echo "no kernel and no bootloader were included"
