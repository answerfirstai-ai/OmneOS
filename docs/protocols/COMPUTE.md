# Compute protocol

`SystemMonitor.snapshot` reads the host. CPU percent comes from two `/proc/stat` samples. Memory
comes from `/proc/meminfo`. Disk comes from `shutil.disk_usage`. Network counters come from
`/proc/net/dev`. GPU data comes from `nvidia-smi` when that command exists. Missing GPU tooling sets
`available` to false. Failures leave numeric fields null. `snapshot()` without a disk path reuses
the last full read for one second. A disk-path read does not replace that cached host snapshot. CPU
percent can be computed from a stored sample when that sample is already older than the sample
interval.

CPU count is the number of `cpuN` lines in `/proc/stat`. A missing file leaves the count null.
Temperature comes from a CPU-like zone under `/sys/class/thermal`. An unrelated zone, a missing
directory, or an unreadable file leaves the temperature null. None of these readers substitute
`os.cpu_count()` or a guessed degree value.

The resource manager records every ask as REQUEST, RESERVE, RUN, or RELEASE. ALLOW moves the ask to
RESERVE and holds the declared CPU, RAM, VRAM, disk, and GPU. Any other decision stays REQUEST and
does not hold capacity. RUN keeps the same hold. RELEASE drops it. The ledger is the sum of RESERVE
and RUN. Host `available_mb` and free VRAM are measurements, so they do not already include these
holds. A request larger than the host measurement is DENY, USE_CLOUD, or USE_DIFFERENT_MODEL. A
request that fits the host but not the remainder is WAIT. The sum of active holds never exceeds the
measured capacity.

Decisions stay ALLOW, WAIT, DEFER, USE_DIFFERENT_MODEL, USE_CLOUD, and DENY. Unknown local RAM or
video memory is DEFER. Unknown memory, disk, CPU count, or GPU telemetry is DEFER. GPU `available`
null means the probe failed or was not answered; that is not treated as a missing device and it does
not fail over to the cloud. `available` false means this probe saw no device, which includes a
missing `nvidia-smi`. It is not a claim about other vendors. A reading at or above 95°C waits only
when the request asks for two or more threads. A null temperature does not wait. CPU or GPU
utilization above 90 percent waits only when that percent was actually read and the request needs
that device. Network counters are reported and are not allocated.

The assembled runtime shares one manager. The task scheduler reserves each selected task. A new
worker reserves the agent manifest. A model load reserves the model manifest and moves the hold to
RUN when the engine maps it. Unload, a failed load, and worker termination release the hold. Reusing
an idle worker does not take a second hold. See `docs/MODELS.md` and `docs/WORKERS.md`.

The model cache records id, size, last access, and location. `load` and `evict` return
`performed: false` because this process does not load weights. The model runtime is a separate path
and still does not download weights.
