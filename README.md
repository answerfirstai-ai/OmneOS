# OMNE OS

OMNE OS is an AI-native operating environment for x86-64 workstations. Linux provides the kernel and
hardware interfaces. This GitHub repository is OmneOS. The software in this tree is OMNE OS.

The core plans an objective, checks permissions, and runs tools or a model provider. The shell is a
separate TypeScript program that talks to the core over HTTP. The core runs without the shell.

## Requirements

- Python 3.12
- Node.js 22
- npm 10

Debian and Ubuntu also need the `python3.12-venv` package.

Verified locally with Python 3.12.3, Node.js 22.14.0, and npm 10.9.7.

## Windows simulation

On Windows 11, paste this into Command Prompt. It installs Git, Python 3.12, and Node.js 22, clones
this branch into `%USERPROFILE%\OmneOS`, builds the shell, and opens the desktop. No API key is
required.

```bat
curl.exe -fL --ssl-no-revoke -o %TEMP%\omne-install.cmd https://raw.githubusercontent.com/answerfirstai-ai/OmneOS/cursor/omne-desktop-windows-92cc/scripts/windows/install-simulation.cmd && %TEMP%\omne-install.cmd
```

The same steps are in `scripts/windows/install-simulation.cmd`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm install
```

`bash scripts/development/bootstrap.sh` runs the same installation.

## Run

```bash
OMNE check
OMNE serve
OMNE execute "write file notes.txt with content hello"
OMNE compute
```

Development settings listen on `http://127.0.0.1:8787`. `GET /health` returns status. `POST /tasks`
runs an objective. `OMNE execute` prints JSON `{"id","status"}` and exits 0 when the task completes,
3 when it is waiting for confirmation, and 1 when it fails.

`NVIDIA_API_KEY` selects the NVIDIA NIM provider when it is present. OMNE still starts, and
`OMNE check` still passes, when the variable is absent. `OMNE models` shows whether NVIDIA is
configured. `OMNE models test nvidia` runs one short completion only when the key is set. The key is
not stored in the repository. See `docs/MODELS.md`.

`XAI_API_KEY` is read in development and testing when the xAI provider is called and no stored
`model/xai` secret is addressed to core. Production does not read that variable. The default route
uses the mock provider, so execute works offline. See `docs/SECRETS.md`.

In another shell, after the core is running:

```bash
npm run build
python3 -m http.server 4173 --directory shell
```

Open `http://127.0.0.1:4173/`.

## Checks

```bash
bash scripts/testing/run-checks.sh
```

## Layout

```text
core/                 Python core
agents/               Agent manifests
models/manifests/     Model manifests
configs/              development, testing, and production TOML
shell/                TypeScript desktop shell
tests/                Python tests
docs/                 Architecture, security, protocols, and roadmap
scripts/linux/        User installer, system packages, rootfs, disk, and ISO builders
system/linux/         User unit, system units, and the Ubuntu 24.04 base pin
```

## USB image and first boot

Build the USB image with the existing ISO script. It uses Ubuntu's kernel from that script. Do not
add another kernel.

```bash
sudo bash scripts/linux/build-iso.sh --dest /var/tmp/OMNE-OS.iso
```

Write that file to a USB stick. `lsblk` shows the stick. Replace `sdX` with that device, not the
computer's disk. This erases the stick.

```bash
sudo dd if=/var/tmp/OMNE-OS.iso of=/dev/sdX bs=4M conv=fsync status=progress
```

Run the PC-boot simulation without writing a disk:

```bash
bash scripts/linux/vm-boot.sh --dry-run /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-boot.sh --run --headless /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --dry-run --iso /var/tmp/OMNE-OS.iso
bash scripts/linux/vm-test.sh --iso /var/tmp/OMNE-OS.iso
```

On Windows, `scripts/windows/install-simulation.cmd` installs the tools, builds the shell, and opens
the desktop. See `docs/ISO_BUILD.md` and `docs/VM_TEST.md`.

The first time the shell starts, OMNE shows setup: a name, a look (color, type, and wallpaper), and
a password. Staged dependencies are listed while that happens. Model weights are not downloaded.
Finishing setup stores a done flag and a password hash in the data directory (`memory/` here,
`/var/lib/omne/memory/` on a machine). Later boots show only the password screen. The correct
password opens the desktop. A wrong password stays on that screen. Setup does not run again.

Colors, type, and wallpaper come from `theme.json` in that data directory.
`OMNE theme apply configs/development/theme.json` writes that file and refuses boot, package, and
unit paths. With no API key and no local model, the desktop still opens after the password. Browse,
files, settings, and Wi-Fi status stay available. Intelligence stays off until an API key is stored
in the secret service or a local model id is selected. The key is not written into `theme.json`, and
model weights are not downloaded. Models can be added, removed, and chosen by difficulty for the
core or for an agent. After unlock, the shell can save an API key or a local model id, and a task
sentence can create an agent the existing worker pool can admit. Task notes are markdown files in a
vault folder under the data directory.

The ISO still boots with `systemd.volatile=state`, so the rest of `/var` stays in memory. Setup
state does not. The image carries a 64 MiB ext4 partition labeled `OMNE-STATE`, appended by the ISO
builder as a file under its temporary work directory, not as a write to a host disk. On a USB stick
written with `dd`, that partition is mounted at `/var/lib/omne` after the volatile `/var` exists.
The setup flag and the password verifier live there, so the next USB boot asks only for the
password. QEMU's ISO test attaches the image as a read-only CD-ROM, which does not expose that
partition, so a virtual reboot of the ISO still starts setup. A machine install keeps the data
directory on its own disk.

## Limits

The development base is Ubuntu 24.04. System packages and `omne.target` start OMNE with the machine.
`scripts/linux/build-base.sh` can write a rootfs and does not install a kernel or a bootloader.
`scripts/linux/build-disk.sh` writes a UEFI disk with systemd-boot and Ubuntu's kernel. The console
is the OMNE checklist, not a desktop. `scripts/linux/build-iso.sh` writes an ISO on Ubuntu 24.04
x86-64 when run as root; otherwise it exits 2 and writes nothing. See `docs/ISO_BUILD.md`.
`scripts/linux/vm-boot.sh --run` starts QEMU when the image and OVMF are present.
`scripts/linux/vm-test.sh` boots the ISO headlessly and is OS-ready only when the OMNE desktop
appears. See `docs/VM_TEST.md`. `OMNE display` reports DRM and labwc readiness and does not start a
compositor. `OMNE windowing` reports the window record and does not command labwc. `OMNE hardware`
reports devices Linux has already published and does not change drivers. `OMNE network` reports the
Linux network stack and does not change it. `OMNE audio` reports the Linux audio stack and does not
open a microphone. `OMNE input` reports configured shortcuts and does not read the keyboard.
`OMNE storage` reports disks and mounts and does not format them. `OMNE applications` reports
installed desktop applications and does not start a shell. `OMNE browser` reports browser
availability and does not launch a browser or import Playwright. `OMNE processes` reports the
process table and does not signal a process. `OMNE updates` reports signed catalog status and does
not install packages. `OMNE recover` explains startup failures and does not erase user data or
reinstall the OS. `OMNE models` reports the model registry and does not download weights. Physical
hardware installation is not implemented.

## License

MIT. See [LICENSE](LICENSE).
