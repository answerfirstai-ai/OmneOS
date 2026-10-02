#!/usr/bin/env bash
# Build a UEFI disk image that keeps setup on an OMNE-STATE partition.
# Ubuntu's linux-image-generic and systemd-boot are reused.
# The image is a file under a temporary directory. No host disk is written.
set -euo pipefail

export PATH="/usr/sbin:/sbin:${PATH}"

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
source "${script_root}/system/linux/state.conf"

refuse_dest() {
  local candidate="$1"
  local resolved
  resolved="$(realpath -m "${candidate}")"
  case "${resolved}" in
    /boot | /boot/* | /efi | /efi/* | /dev | /dev/*)
      echo "refusing to write a disk at ${candidate}; no disk was written" >&2
      exit 2
      ;;
  esac
  if [[ -b "${resolved}" || -b "${candidate}" ]]; then
    echo "refusing to write a disk to block device ${candidate}; no disk was written" >&2
    exit 2
  fi
  local repo_real
  repo_real="$(realpath -m "${script_root}")"
  case "${resolved}" in
    "${repo_real}" | "${repo_real}"/*)
      echo "refusing to write a disk inside the source tree (${candidate}); no disk was written" >&2
      exit 2
      ;;
  esac
}

if [[ -n "${dest}" ]]; then
  refuse_dest "${dest}"
fi

echo "firmware: UEFI"
echo "bootloader: systemd-boot"
echo "kernel: linux-image-generic"
echo "base: ${OMNE_BASE_ID} ${OMNE_BASE_VERSION} (${OMNE_BASE_CODENAME})"
echo "init: state-disk initramfs (build-disk.sh and build-iso.sh use systemd)"
echo "compositor: labwc on the full image"
echo "state: ${OMNE_STATE_LABEL} mounted at ${OMNE_STATE_MOUNT}"
echo "volatile /var: kept"
echo "host disk: not written"

if [[ "${dry_run}" -eq 1 ]]; then
  echo "dry-run: no disk was written"
  exit 0
fi

if [[ -z "${dest}" ]]; then
  echo "dest is required; no disk was written" >&2
  exit 2
fi
dest="$(realpath -m "${dest}")"
refuse_dest "${dest}"
if [[ -e "${dest}" ]]; then
  echo "dest already exists; no disk was written" >&2
  exit 2
fi
for tool in curl gzip cpio python3 dpkg-deb sgdisk mkfs.vfat mkfs.ext4 mcopy mmd debugfs; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "${tool} is missing; no disk was written" >&2
    exit 2
  fi
done
if [[ ! -x /usr/bin/busybox && ! -x /bin/busybox ]]; then
  echo "busybox is missing; no disk was written" >&2
  exit 2
fi

work=""
cleanup() {
  local status=$?
  if [[ -n "${work}" ]]; then
    rm -rf "${work}" 2>/dev/null || sudo -n rm -rf "${work}"
  fi
  if [[ "${status}" -ne 0 && -n "${dest}" && -f "${dest}" ]]; then
    rm -f "${dest}"
  fi
  exit "${status}"
}
trap cleanup EXIT

work="$(mktemp -d /var/tmp/omne-state-disk.XXXXXX)"
mirror="${OMNE_BASE_MIRROR%/}"

echo "resolving ${OMNE_BASE_CODENAME} packages"
python3 - "${mirror}" "${OMNE_BASE_CODENAME}" "${work}/debs" <<'PY'
import gzip
import sys
import urllib.request
from pathlib import Path

mirror, codename, dest = sys.argv[1], sys.argv[2], Path(sys.argv[3])
dest.mkdir(parents=True, exist_ok=True)

def packages(component: str) -> list[dict[str, str]]:
    url = f"{mirror}/dists/{codename}/{component}/binary-amd64/Packages.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        blob = response.read()
    text = gzip.decompress(blob).decode("utf-8", "replace")
    blocks = []
    for chunk in text.split("\n\n"):
        fields: dict[str, str] = {}
        key = ""
        for line in chunk.splitlines():
            if not line:
                continue
            if line.startswith(" ") and key:
                fields[key] = fields[key] + " " + line.strip()
            elif ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        if fields.get("Package"):
            blocks.append(fields)
    return blocks

index = {item["Package"]: item for item in packages("main")}
index.update({item["Package"]: item for item in packages("universe")})

def require(name: str) -> dict[str, str]:
    found = index.get(name)
    if found is None or "Filename" not in found:
        raise SystemExit(f"{name} is not in the Ubuntu package index")
    return found

generic = require("linux-image-generic")
image_name = ""
for token in generic.get("Depends", "").replace(",", " ").split():
    if token.startswith("linux-image-") and token.endswith("-generic") and token != "linux-image-generic":
        image_name = token
        break
if not image_name:
    raise SystemExit("linux-image-generic does not name a kernel package")
image = require(image_name)
modules_name = ""
for token in image.get("Depends", "").replace(",", " ").split():
    if token.startswith("linux-modules-") and token.endswith("-generic"):
        modules_name = token
        break
boot = require("systemd-boot-efi")
selected = [("linux-image.deb", image), ("systemd-boot-efi.deb", boot)]
if modules_name:
    selected.append(("linux-modules.deb", require(modules_name)))
(dest / "packages.txt").write_text(
    "\n".join(f"{name} {item['Filename']}" for name, item in selected) + "\n",
    encoding="utf-8",
)
for name, item in selected:
    url = f"{mirror}/{item['Filename']}"
    target = dest / name
    print(f"fetching {item['Package']}", flush=True)
    urllib.request.urlretrieve(url, target)
PY

mkdir -p "${work}/extract/image" "${work}/extract/efi" "${work}/extract/modules"
dpkg-deb -x "${work}/debs/linux-image.deb" "${work}/extract/image"
dpkg-deb -x "${work}/debs/systemd-boot-efi.deb" "${work}/extract/efi"
if [[ -f "${work}/debs/linux-modules.deb" ]]; then
  dpkg-deb -x "${work}/debs/linux-modules.deb" "${work}/extract/modules"
fi

kernel="$(find "${work}/extract/image/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | sort | tail -n 1)"
efi_source="${work}/extract/efi/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
if [[ -z "${kernel}" || ! -f "${efi_source}" ]]; then
  echo "kernel or systemd-boot is missing; no disk was written" >&2
  exit 2
fi
kver="${kernel##*/vmlinuz-}"

init="${work}/initramfs"
mkdir -p "${init}/bin" "${init}/usr/lib/omne" "${init}/usr/bin"
busybox="$(command -v busybox)"
cp "${busybox}" "${init}/bin/busybox"
"${init}/bin/busybox" --install -s "${init}/bin"
cp "${script_root}/system/linux/state-disk-init" "${init}/init"
cp "${script_root}/system/linux/state-gate.py" "${init}/usr/lib/omne/state-gate.py"
chmod 755 "${init}/init" "${init}/usr/lib/omne/state-gate.py"

python3 - "${script_root}" "${init}" "${work}/extract/modules" "${kver}" <<'PY'
import shutil
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1])
init = Path(sys.argv[2])
modules_root = Path(sys.argv[3])
kver = sys.argv[4]

venv = repo / ".venv" / "bin" / "python"
python = venv if venv.is_file() else Path(sys.executable)
binary = python.resolve()
stdlib = Path(
    subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('stdlib'))"],
        text=True,
    ).strip()
)
site = Path(
    subprocess.check_output(
        [str(python), "-c", "import pathlib, pydantic; print(pathlib.Path(pydantic.__file__).resolve().parent.parent)"],
        text=True,
    ).strip()
)

def install(src: Path, root: Path) -> None:
    dest = root / src.as_posix().lstrip("/")
    if dest.exists() or dest.is_symlink():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        link = src.readlink()
        dest.symlink_to(link)
        if link.is_absolute():
            install(Path(link), root)
        else:
            expected = dest.parent / link
            expected.parent.mkdir(parents=True, exist_ok=True)
            if not expected.exists() and not expected.is_symlink():
                shutil.copy2(src.resolve(), expected)
        return
    shutil.copy2(src, dest)


def libs_of(path: Path) -> list[Path]:
    found: list[Path] = []
    try:
        text = subprocess.check_output(["ldd", str(path)], text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return found
    for line in text.splitlines():
        stripped = line.strip()
        if "=>" in stripped:
            parts = stripped.split()
            if len(parts) >= 3 and parts[2].startswith("/"):
                found.append(Path(parts[2]))
        elif stripped.startswith("/") and "ld-linux" in stripped:
            found.append(Path(stripped.split()[0]))
    return found

def closure(paths: list[Path]) -> None:
    pending = [path for path in paths if path.exists()]
    seen: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            text = subprocess.check_output(["ldd", str(current)], text=True, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            text = ""
        for line in text.splitlines():
            stripped = line.strip()
            if "=>" in stripped:
                parts = stripped.split()
                if len(parts) >= 3 and parts[2].startswith("/"):
                    pending.append(Path(parts[2]))
            elif stripped.startswith("/") and "ld-linux" in stripped:
                pending.append(Path(stripped.split()[0]))
        install(current, init)

shutil.copy2(binary, init / "usr/bin/python3")
(init / "usr/bin/python3").chmod(0o755)
target_stdlib = init / "usr/lib" / stdlib.name
skip = {"test", "tests", "ensurepip", "idlelib", "turtledemo", "tkinter", "__pycache__"}
for path in stdlib.rglob("*"):
    relative = path.relative_to(stdlib)
    if any(part in skip for part in relative.parts):
        continue
    if path.name.startswith("_tkinter") or path.name.startswith("_dbm"):
        continue
    destination = target_stdlib / relative
    if path.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
    elif path.is_symlink() or path.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            destination.symlink_to(path.readlink())
        else:
            shutil.copy2(path, destination)

omne_dest = init / "usr/lib/omne/python/omne"
omne_dest.mkdir(parents=True, exist_ok=True)
for name in ("__init__.py", "firstboot.py"):
    shutil.copy2(repo / "omne" / name, omne_dest / name)
site_dest = init / "usr/lib/omne/site"
site_dest.mkdir(parents=True, exist_ok=True)
for name in ("pydantic", "pydantic_core", "annotated_types", "typing_extensions.py", "typing_extensions"):
    source = site / name
    if source.exists():
        if source.is_dir():
            shutil.copytree(source, site_dest / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, site_dest / name)

native = list((site_dest / "pydantic_core").glob("*.so")) if (site_dest / "pydantic_core").is_dir() else []
crypt = list(target_stdlib.glob("lib-dynload/*.so"))
closure([*native, *crypt, *libs_of(binary)])

config = next(modules_root.rglob(f"config-{kver}"), None)
builtin = False
if config is not None:
    flags = {}
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            flags[key] = value
    builtin = flags.get("CONFIG_EXT4_FS") == "y" and flags.get("CONFIG_VIRTIO_BLK") == "y"
if builtin:
    print("kernel has ext4 and virtio-blk built in")
    raise SystemExit(0)

module_dir = modules_root / "lib/modules" / kver
if not module_dir.is_dir():
    raise SystemExit("kernel modules are required and were not extracted")
name_to_path: dict[str, Path] = {}
for ko in module_dir.rglob("*.ko*"):
    name = subprocess.check_output(["modinfo", "-F", "name", str(ko)], text=True).strip()
    if name:
        name_to_path[name] = ko

def dependencies(ko: Path) -> list[str]:
    text = subprocess.check_output(["modinfo", "-F", "depends", str(ko)], text=True).strip()
    return [item for item in text.split(",") if item]

order: list[Path] = []
seen: set[str] = set()

def add(name: str) -> None:
    if name in seen:
        return
    seen.add(name)
    ko = name_to_path.get(name)
    if ko is None:
        return
    for item in dependencies(ko):
        add(item)
    order.append(ko)

for seed in ("virtio_blk", "ext4"):
    add(seed)
if not order:
    raise SystemExit("ext4 or virtio_blk module was not found")
destination_root = init / "lib/modules" / kver
lines = []
for ko in order:
    relative = ko.relative_to(module_dir)
    target = destination_root / relative
    target = target.with_suffix("") if target.name.endswith(".zst") else target
    if ko.name.endswith(".ko.zst"):
        target = target.with_name(target.name[:-4]) if target.name.endswith(".zst") else target
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["zstd", "-d", "-f", "-o", str(target), str(ko)], check=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ko, target)
    lines.append(str(Path("/") / target.relative_to(init)))
(init / "etc/omne").mkdir(parents=True, exist_ok=True)
(init / "etc/omne/modules.load").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"packed {len(lines)} kernel modules")
PY

if ! command -v ldconfig >/dev/null 2>&1 || ! ldconfig -r "${init}" >/dev/null 2>&1; then
  echo "ldconfig skipped; the init exports LD_LIBRARY_PATH"
fi
mkdir -p "${init}/lib/x86_64-linux-gnu" "${init}/lib64"
if [[ ! -e "${init}/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" ]]; then
  cp -a "$(readlink -f /lib64/ld-linux-x86-64.so.2)" "${init}/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
fi
ln -sfn ../lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 "${init}/lib64/ld-linux-x86-64.so.2"

if sudo -n env PYTHONDONTWRITEBYTECODE=1 PYTHONHOME=/usr PYTHONPATH=/usr/lib/omne/python:/usr/lib/omne/site LD_LIBRARY_PATH=/lib/x86_64-linux-gnu chroot "${init}" /usr/bin/python3 -c 'from omne.firstboot import boot_gate; from pathlib import Path; print(boot_gate(Path("/tmp/missing")))' | grep -qx setup; then
  echo "guest python can read the boot gate"
else
  echo "guest python cannot import the boot gate; no disk was written" >&2
  exit 2
fi

mkdir -p "${work}/esp/EFI/BOOT" "${work}/esp/EFI/systemd" "${work}/esp/loader/entries" "${work}/esp/omne"
cp "${efi_source}" "${work}/esp/EFI/BOOT/BOOTX64.EFI"
cp "${efi_source}" "${work}/esp/EFI/systemd/systemd-bootx64.efi"
cp "${kernel}" "${work}/esp/omne/vmlinuz"
(
  cd "${init}"
  find . -print0 | cpio --null -o --format=newc --quiet
) | gzip -1 > "${work}/esp/omne/initrd.img"
cat > "${work}/esp/loader/loader.conf" <<'LOADER'
default omne.conf
timeout 0
editor no
LOADER
cat > "${work}/esp/loader/entries/omne.conf" <<ENTRY
title OMNE
linux /omne/vmlinuz
initrd /omne/initrd.img
options rdinit=/init root=LABEL=omne rootwait console=tty0 console=ttyS0 systemd.unit=multi-user.target systemd.volatile=state
ENTRY

mkdir -p "${work}/root/etc/omne"
cp "${script_root}/system/linux/state.conf" "${work}/root/etc/omne/state.conf"
cat > "${work}/root/etc/fstab" <<FSTAB
LABEL=omne / ext4 defaults 0 1
LABEL=${OMNE_STATE_LABEL} ${OMNE_STATE_MOUNT} ext4 nofail,noatime,x-systemd.device-timeout=10s,x-systemd.after=var.mount,x-systemd.before=omne-core.service 0 2
FSTAB

esp_bytes="$(du -sb "${work}/esp" | awk '{print $1}')"
esp_mib=$(( (esp_bytes / 1048576) + 32 ))
if (( esp_mib < 96 )); then
  esp_mib=96
fi

echo "writing disk image"
bash "${script_root}/scripts/linux/assemble-disk-image.sh" \
  --dest "${dest}" \
  --esp-dir "${work}/esp" \
  --root-dir "${work}/root" \
  --esp-mib "${esp_mib}" \
  --root-mib 32 \
  --state-mib 64 \
  --state-label "${OMNE_STATE_LABEL}"

echo "state disk written to ${dest}"
echo "second boot reads ${OMNE_STATE_LABEL} and shows the password gate"
echo "no host disk and no block device were written"
