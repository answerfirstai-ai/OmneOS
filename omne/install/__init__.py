"""Install OMNE onto a directory root without touching a host disk."""

from omne.install.machine import InstallError, InstallRecord, boot_settings, install_machine

__all__ = ["InstallError", "InstallRecord", "boot_settings", "install_machine"]
