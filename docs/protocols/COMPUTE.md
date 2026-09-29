# Compute protocol

`SystemMonitor.snapshot` reads the host. CPU percent comes from two `/proc/stat` samples. Memory
comes from `/proc/meminfo`. Disk comes from `shutil.disk_usage`. Network counters come from
`/proc/net/dev`. GPU data comes from `nvidia-smi` when that command exists. Missing GPU tooling sets
`available` to false. Failures leave numeric fields null.

The allocator returns ALLOW, WAIT, DEFER, USE_DIFFERENT_MODEL, USE_CLOUD, or DENY. A local model
with unknown RAM is DEFER. A RAM request above available memory is USE_CLOUD when a cloud model is
allowed, otherwise DENY. CPU above 90 percent with two or more threads is WAIT.

The model cache records id, size, last access, and location. `load` and `evict` return
`performed: false` because this process does not load weights.
