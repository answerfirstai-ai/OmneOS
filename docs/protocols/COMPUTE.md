# Compute protocol

`SystemMonitor.snapshot` reads the host. CPU percent comes from two `/proc/stat` samples. Memory
comes from `/proc/meminfo`. Disk comes from `shutil.disk_usage`. Network counters come from
`/proc/net/dev`. GPU data comes from `nvidia-smi` when that command exists. Missing GPU tooling sets
`available` to false. Failures leave numeric fields null. `snapshot()` without a disk path reuses
the last full read for one second. A disk-path read does not replace that cached host snapshot. CPU
percent can be computed from a stored sample when that sample is already older than the sample
interval.

The allocator returns ALLOW, WAIT, DEFER, USE_DIFFERENT_MODEL, USE_CLOUD, or DENY. A local model
with unknown RAM is DEFER. A RAM request above available memory is USE_CLOUD when a cloud model is
allowed, otherwise DENY. CPU above 90 percent with two or more threads is WAIT.

The model cache records id, size, last access, and location. `load` and `evict` return
`performed: false` because this process does not load weights. The model runtime is a separate path:
it asks this allocator before mapping a model an engine already has, and it still does not download
weights. See `docs/MODELS.md`.
