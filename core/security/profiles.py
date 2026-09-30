"""Isolation profiles for OMNE components.

A profile names the Linux controls that component is allowed to have. SYSTEM
is the host. OMNE code cannot select it. Ceilings are hard limits, not a
measurement of free memory.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProfileName(StrEnum):
    """Who is asking to act."""

    SYSTEM = "SYSTEM"
    CORE = "CORE"
    AGENT = "AGENT"
    WORKER = "WORKER"
    MODEL = "MODEL"
    SHELL = "SHELL"
    APPLICATION = "APPLICATION"


class ResourceCeiling(BaseModel):
    """Hard limits for one profile. A claim above a ceiling is denied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ram_mb: int = Field(ge=0)
    vram_mb: int = Field(ge=0)
    cpu_threads: int = Field(ge=0)
    pids: int = Field(ge=0)
    file_mb: int = Field(ge=0)
    cpu_seconds: int = Field(ge=0)
    nofile: int = Field(ge=0)


class Profile(BaseModel):
    """The sandbox contract for one component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ProfileName
    user: str
    group: str
    host_spawn: bool
    network: str
    capabilities: tuple[str, ...] = ()
    ceiling: ResourceCeiling
    systemd: tuple[str, ...] = ()


_WORKER_CEILING = ResourceCeiling(
    ram_mb=8192,
    vram_mb=0,
    cpu_threads=8,
    pids=256,
    file_mb=1024,
    cpu_seconds=120,
    nofile=256,
)

_CORE_SANDBOX = (
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "PrivateDevices=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectKernelLogs=true",
    "ProtectControlGroups=true",
    "ProtectClock=true",
    "ProtectHostname=true",
    "RestrictSUIDSGID=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
    "RestrictRealtime=true",
    "RestrictNamespaces=true",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "SystemCallErrorNumber=EPERM",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    "IPAddressDeny=any",
    "IPAddressAllow=localhost",
    "UMask=0077",
    "DevicePolicy=closed",
    "MemoryMax=1G",
    "TasksMax=64",
    "CPUQuota=200%",
    "LimitNOFILE=1024",
    "InaccessiblePaths=-/boot -/efi -/root -/etc/shadow -/etc/gshadow -/etc/sudoers -/etc/ssh",
)

_SHELL_SANDBOX = (
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "PrivateDevices=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectKernelLogs=true",
    "ProtectControlGroups=true",
    "ProtectClock=true",
    "ProtectHostname=true",
    "ProtectProc=invisible",
    "RestrictSUIDSGID=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
    "RestrictRealtime=true",
    "RestrictNamespaces=true",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "SystemCallErrorNumber=EPERM",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    "IPAddressDeny=any",
    "IPAddressAllow=localhost",
    "UMask=0077",
    "DevicePolicy=closed",
    "MemoryMax=256M",
    "TasksMax=32",
    "ReadOnlyPaths=/usr/share/omne/shell",
    "InaccessiblePaths=-/boot -/efi -/root -/etc/shadow -/etc/gshadow -/etc/sudoers "
    "-/etc/ssh -/etc/omne -/var/lib/omne",
)


PROFILES: dict[ProfileName, Profile] = {
    ProfileName.SYSTEM: Profile(
        name=ProfileName.SYSTEM,
        user="root",
        group="root",
        host_spawn=False,
        network="host",
        capabilities=("host",),
        ceiling=ResourceCeiling(
            ram_mb=0,
            vram_mb=0,
            cpu_threads=0,
            pids=0,
            file_mb=0,
            cpu_seconds=0,
            nofile=0,
        ),
    ),
    ProfileName.CORE: Profile(
        name=ProfileName.CORE,
        user="omne",
        group="omne",
        host_spawn=False,
        network="loopback",
        ceiling=ResourceCeiling(
            ram_mb=1024,
            vram_mb=0,
            cpu_threads=2,
            pids=64,
            file_mb=1024,
            cpu_seconds=0,
            nofile=1024,
        ),
        systemd=_CORE_SANDBOX,
    ),
    ProfileName.AGENT: Profile(
        name=ProfileName.AGENT,
        user="omne-agent",
        group="omne-agent",
        host_spawn=False,
        network="none",
        ceiling=_WORKER_CEILING,
    ),
    ProfileName.WORKER: Profile(
        name=ProfileName.WORKER,
        user="omne-agent",
        group="omne-agent",
        host_spawn=True,
        network="none",
        ceiling=_WORKER_CEILING,
    ),
    ProfileName.MODEL: Profile(
        name=ProfileName.MODEL,
        user="omne-agent",
        group="omne-agent",
        host_spawn=False,
        network="loopback",
        ceiling=ResourceCeiling(
            ram_mb=8192,
            vram_mb=16384,
            cpu_threads=4,
            pids=1,
            file_mb=1024,
            cpu_seconds=0,
            nofile=64,
        ),
    ),
    ProfileName.SHELL: Profile(
        name=ProfileName.SHELL,
        user="omne",
        group="omne",
        host_spawn=False,
        network="loopback",
        ceiling=ResourceCeiling(
            ram_mb=256,
            vram_mb=0,
            cpu_threads=1,
            pids=32,
            file_mb=0,
            cpu_seconds=0,
            nofile=64,
        ),
        systemd=_SHELL_SANDBOX,
    ),
    ProfileName.APPLICATION: Profile(
        name=ProfileName.APPLICATION,
        user="omne-app",
        group="omne-app",
        host_spawn=False,
        network="none",
        ceiling=ResourceCeiling(
            ram_mb=2048,
            vram_mb=0,
            cpu_threads=2,
            pids=64,
            file_mb=256,
            cpu_seconds=60,
            nofile=128,
        ),
    ),
}


def profile_for(name: str) -> Profile | None:
    """Return a profile. An unknown name is absent, which callers deny."""

    try:
        return PROFILES[ProfileName(name)]
    except ValueError:
        return None
