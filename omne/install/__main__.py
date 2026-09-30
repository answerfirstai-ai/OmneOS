"""Install OMNE onto a directory root. Block devices are refused."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omne.install.machine import InstallError, install_machine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install OMNE onto a directory root.")
    parser.add_argument("--dest", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", default="")
    args = parser.parse_args(argv)
    source = Path(args.source) if args.source else Path(__file__).resolve().parents[2]
    try:
        record = install_machine(source, Path(args.dest), dry_run=args.dry_run)
    except InstallError as exc:
        sys.stderr.write(f"{exc.message}\n")
        return 2
    print(f"install root {args.dest}")
    print("persistent state: yes" if record["persistent_state"] else "persistent state: no")
    print("volatile state: yes" if record["volatile_state"] else "volatile state: no")
    print(
        "nvidia boot dependency: yes"
        if record["nvidia_boot_dependency"]
        else "nvidia boot dependency: no"
    )
    print("disk format: yes" if record["disk_format"] else "disk format: no")
    print("bootloader: written" if record["bootloader_written"] else "bootloader: not written")
    print(f"shell surface: {record['shell_surface']}")
    if args.dry_run:
        print("dry-run: no files were written")
    else:
        print("installed machine root; no disk was formatted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
