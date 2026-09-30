# Update architecture

Ubuntu's apt and dpkg remain the package tools. OMNE does not ship a package manager. The update
layer checks signed metadata, verifies artifacts, records history, and prepares a pending boot slot.
It does not install packages on the development host, and it does not run `apt-get` or `dpkg -i`.

```text
signed catalog
      │
      ▼
OpenSSL signature check
      │
      ▼
sha256 and, for a .deb, dpkg-deb --info
      │
      ▼
apt command plan          ← not executed
      │
      ▼
pending slot in OMNE state
      │
      ▼
commit after reboot       ← explicit, and it does not write the bootloader
      │
      ▼
rollback to the booted generation
```

`GET /updates` and `OMNE updates` report status. `OMNE updates --dry-run --catalog PATH` prints the
plan. A catalog without `--dry-run` exits 2. `POST /updates` is 404.

## Channels

| Channel     | Artifact                                 | Install plan                                     |
| ----------- | ---------------------------------------- | ------------------------------------------------ |
| linux       | Ubuntu packages                          | `apt-get update`, then `apt-get upgrade`         |
| omne        | `omne-core`, `omne-shell`, `omne-system` | `apt-get install` of those debs                  |
| application | Another Debian package                   | `apt-get install` of that deb                    |
| model       | A signed file, not a deb                 | Staged only. The model runtime does not load it. |

A dry-run puts `apt-get -s` in front of upgrade and install. The core never runs the list. Linux
updates are marked reboot-required because a kernel package may be in the set. Model and application
updates reboot only when the signed catalog says so.

## Verification

Each channel directory holds `updates.json` and `updates.json.sig`. `trusted.pub` is an Ed25519
public key. OpenSSL `pkeyutl -verify` checks the catalog before any package is hashed. A missing
tool, a missing signature, or a bad signature rejects the channel.

An OMNE catalog without a signature is an unsigned system package and is rejected. An OMNE catalog
that names any package other than `omne-core`, `omne-shell`, or `omne-system` is rejected. Package
filenames stay inside the channel directory. The digest and size must match. A `.deb` must also pass
`dpkg-deb --info`. None of those checks install the package.

## State

History lives in the data directory as `updates/state.json`. That file is the update record, not the
host package database.

| Slot | Meaning                                                |
| ---- | ------------------------------------------------------ |
| A    | One boot slot. The machine starts on A.                |
| B    | The other slot. A staged update is written here first. |

Phases are `checked`, `downloaded`, `verified`, `installing`, `staged`, `installed`, `interrupted`,
`failed`, `rolled_back`, and `rejected`. Staging copies verified files under `updates/staging` and
leaves the booted slot unchanged. `commit` records the pending slot as booted after a reboot would
have happened. It does not reboot and it does not change systemd-boot. Rollback of a staged update
discards the pending slot. Rollback after commit restores the previous installed generation.

An `installing` generation found on the next read becomes `interrupted`. The booted slot is not
advanced.

## What this revision does not do

The development host is not updated automatically. `automatic` and `host_updated` stay false. Apt is
the planned installer for a later root step, after the same signature and hash checks. Atomic A/B
root filesystems and bootloader entries are the slot model above. This revision stores that model
and does not write either root or the bootloader.
