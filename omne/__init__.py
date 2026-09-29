"""OMNE packages that sit beside Core.

Core depends on these interfaces. Compositor-specific code stays inside a provider.
Window changes stay behind a grant and are not sent to the compositor.
Hardware discovery reads Linux sysfs and proc and does not configure devices.
"""
