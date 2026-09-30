"""Apt commands for a verified catalog.

The lists are the distribution's package tools. This module does not run them.
"""

from __future__ import annotations

from omne.updates.model import ChannelCatalog


def install_commands(catalog: ChannelCatalog, *, dry_run: bool) -> list[list[str]]:
    """Return the apt plan for one channel. Model artifacts are not apt packages."""

    if catalog.channel == "model":
        return []
    if catalog.channel == "linux":
        upgrade = ["apt-get", "upgrade"]
        if dry_run:
            upgrade = ["apt-get", "-s", "upgrade"]
        return [["apt-get", "update"], upgrade]
    packages = [package.filename for package in catalog.packages]
    install = ["apt-get", "install", "--no-download", *packages]
    if dry_run:
        install = ["apt-get", "-s", "install", "--no-download", *packages]
    return [install]
