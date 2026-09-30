# Model protocol

A provider implements `generate`, `stream`, and `tool_call`. `tool_call` returns a name and
arguments. It does not execute the tool.

Manifests live in `models/manifests/*.toml`. Fields are `id`, `provider` (`mock`, `xai`, or
`local`), `model_name`, `capabilities`, `local`, `priority`, `requirements`, and the metrics
`cost_input`, `cost_output`, and `latency`. Unknown metrics stay the string `unknown`.

The router keeps models that declare every requested capability, sorts by priority, and accepts the
first ALLOW decision. The shipped mock manifest uses priority 0, so offline runs select it. The
local manifest sets `ram_known` and `vram_known` to false, so the allocator defers it instead of
inventing hardware numbers. `ModelRuntime` is the load path. It uses an adapter, enforces the
context window and the allocator, and does not download weights. See `docs/MODELS.md`.

xAI calls `POST {base}/chat/completions`. In development and testing, a missing `XAI_API_KEY` and a
missing `model/xai` secret raise `ProviderError` with code `configuration` before any HTTP request.
Production uses the stored secret and does not read the variable. Authentication failures are not
retried. Timeouts, 429, and 5xx responses retry up to `xai_max_retries`. See `docs/SECRETS.md`.
