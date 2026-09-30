# Models

A model is a system resource. The registry holds its metadata. The runtime loads it, runs it, and
unloads it. The router selects among models the runtime says are available.

```text
model runtime → compute allocator → worker record → model router
```

The runtime does not download weights. It does not assume NVIDIA, AMD, or a machine with no GPU. An
adapter reports an accelerator only when that adapter already knows one. Otherwise the health field
stays `unknown`. The mock adapter reports `none` because it does not use an accelerator.

## Registry

Manifests live in `models/manifests/*.toml`. A manifest names the provider (`mock`, `xai`, or
`local`), the model name, capabilities, whether it is local, a context window when one is known, and
resource requirements. Unknown memory stays unknown. `local-default` ships with `ram_known` and
`vram_known` false, so the allocator defers it instead of inventing a size.

## Engines

Core depends on an engine protocol: probe, residency, load, unload, generate, stream, and cancel.
Two adapters ship with OMNE.

- `mock` keeps a slot in memory. Tests and the default route use it. It does not read a weight file.
- `openai-compatible` talks to `OMNE_LOCAL_MODEL_BASE_URL` when that URL is set. It asks the server
  which models it already has. Load succeeds only for a listed name. An empty URL does not open a
  connection.

A cloud provider such as xAI is not loaded as a local weight. Its own provider still serves requests
when a key is configured.

## Lifecycle

```text
AVAILABLE → LOADING → LOADED → RUNNING → IDLE
LOADED or IDLE → UNLOADING → AVAILABLE
LOADING or RUNNING → FAILED
FAILED → LOADING
```

`UNAVAILABLE` means the provider is not configured or the local engine does not already have the
model. `RUNNING` is an inference. `BUSY` remains a recognized label for older records. Ordinary task
execution does not call load, so a file write does not emit `model.loaded`.

`model.loading`, `model.loaded`, `model.running`, `model.idle`, `model.unloading`, `model.unloaded`,
`model.failed`, and `model.cancelled` carry the model id, the lifecycle, and the engine name. They
do not carry a filesystem path or a prompt.

## Limits

Load reserves the model requirements on the shared resource manager, with cloud fallback disabled.
Unknown local RAM is deferred. RAM above the snapshot is denied. RAM that fits the host but is
already reserved waits. A video-memory requirement is deferred when GPU telemetry is unavailable,
and denied when the snapshot reports that this probe saw no GPU or not enough free memory. The
refusal names the resource, not a vendor. A successful load moves the reservation to RUN. Unload and
a failed load release it.

A context window on the manifest is enforced with a four-characters-per-token estimate of the system
text plus the prompt. A missing window is not replaced with a guessed cap. Cancellation stops an
in-flight request between chunks and returns the model to `IDLE`. It does not signal a process.

Load can record a worker id. An unknown or finished worker is refused. The worker stays an in-memory
record.

`ModelCache.load` and `ModelLifecycle.load` still report that they did not map weights.
`ModelRuntime.load` is the path that maps a resident model.
