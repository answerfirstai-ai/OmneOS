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
