# Storage

Linux owns the disks. OMNE reads the layout those disks already have.

```text
sysfs and proc/mounts
        │
        ▼
omne.storage provider   ← mock layout, or a Linux read
        │
        ▼
StorageService          ← disk, partition, mount, and space events
        │
        ▼
OMNE Core               ← GET /storage, OMNE storage
        │
        ▼
filesystem tools        ← OMNE paths only
```

Core imports `omne.storage`. Discovery does not format a disk, change a partition table, open a raw
device, or write a bootloader. `raw_access` and `formatting` stay false. There is no
`POST /storage`.

## What a read contains

| Record     | Fields                                                                             |
| ---------- | ---------------------------------------------------------------------------------- |
| Disk       | Name, `/dev` identifier, size, removable, read-only, rotational, protected         |
| Partition  | Disk, role, size, removable, read-only, protected                                  |
| Filesystem | Device, mount, type, read-only, removable, used bytes, free bytes, role, protected |

A missing size or a mount directory that cannot be measured stays null. Loop and ram devices are
skipped. Fixed disks are protected. Removable disks are protected only when they carry a system,
boot, or device filesystem. Roles are `system`, `boot`, `device`, `user`, `omne`, and `unknown`.

`/` , `/usr`, `/var`, and `/opt` are system mounts. `/boot`, `/boot/efi`, `/efi`, and `efivarfs` are
boot mounts. `devtmpfs` and anything under `/dev` are device mounts. `/home` and `/media` are user
mounts.

## Path classes

Filesystem tools ask `classify_path` before they read or write. The class is decided from the
resolved path, including a symlink target.

| Class    | Meaning                                                                                     | Filesystem tools |
| -------- | ------------------------------------------------------------------------------------------- | ---------------- |
| `OMNE`   | The configured workspace, when that root is not itself protected                            | Allowed          |
| `USER`   | A non-protected path outside the workspace, such as a home directory                        | Denied           |
| `SYSTEM` | `/etc`, `/proc`, `/sys`, `/usr`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/opt`, `/run`, and `/` | Denied           |
| `BOOT`   | `/boot`, `/efi`, and bootloader paths under them                                            | Denied           |
| `DEVICE` | `/dev` and block-device nodes                                                               | Denied           |

A workspace set to `/` does not make the rest of the machine writable. Traversal with `..`, a
symlink out of the workspace, and a symlink into `/etc`, `/boot`, or `/dev` are denied. A path that
exists but cannot be stat'd is inaccessible and is denied. `.git` stays denied after classification.

`wipefs`, `sfdisk`, `gdisk`, `bootctl`, and the `mkfs.*` commands stay on the command deny list.

## Events

| Event                                                   | When                                              |
| ------------------------------------------------------- | ------------------------------------------------- |
| `storage.disk.added` / `storage.disk.removed`           | A disk appears or disappears after the first read |
| `storage.partition.added` / `storage.partition.removed` | A partition appears or disappears                 |
| `storage.mount.added` / `storage.mount.removed`         | A mount appears or disappears                     |
| `storage.space.changed`                                 | Used or free bytes change for a mount             |

The first read is a baseline and emits nothing. Payloads name the disk or the mount. They do not
contain file contents.

## Providers

| Provider | When                                                   |
| -------- | ------------------------------------------------------ |
| mock     | `OMNE_ENVIRONMENT=testing`, and any non-Linux platform |
| linux    | Development and production on Linux                    |

The Linux provider reads `/sys/block` and `/proc/mounts`, and calls `statvfs` on the mount
directory. It does not open `/dev`.
