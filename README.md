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

`XAI_API_KEY` is read only when the xAI provider is called. The default route uses the mock
provider, so execute works offline.

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
scripts/linux/        User installer, system packages, rootfs builder, image check, VM check
system/linux/         User unit, system units, and the Ubuntu 24.04 base pin
```

## Limits

The development base is Ubuntu 24.04. System packages and `omne.target` start OMNE with the machine.
`scripts/linux/build-base.sh` can write a rootfs and does not install a kernel or a bootloader. No
`OMNE-OS.iso` is produced. `scripts/linux/build-iso.sh` exits 2 and does not write an image.
`scripts/linux/vm-boot.sh` does not start a virtual machine. Physical hardware installation is not
implemented.

## License

MIT. See [LICENSE](LICENSE).
