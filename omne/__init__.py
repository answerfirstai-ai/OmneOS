"""OMNE packages that sit beside Core.

Core depends on these interfaces. Compositor-specific code stays inside a provider.
Window changes stay behind a grant and are not sent to the compositor.
Hardware discovery reads Linux sysfs and proc and does not configure devices.
Network discovery reads the Linux stack and does not replace it.
Audio discovery reads PipeWire or ALSA and does not open a microphone.
Input bindings come from configuration and do not read the keyboard stream.
Storage inspection reads disks and mounts and does not format them.
Application discovery reads desktop entries and does not start a shell.
Browser integration keeps the application, automation, research, and rendering layers apart
and does not import Playwright.
Process inspection reads the process table and does not signal the host.
Secret storage keeps credentials out of configuration, logs, and task records.
Update planning checks signed catalogs and does not install packages on the host.
"""
