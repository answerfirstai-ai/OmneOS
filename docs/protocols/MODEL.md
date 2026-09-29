# Model protocol

A provider implements `generate`, `stream`, and `tool_call`. `tool_call` returns a name and
arguments. It does not execute the tool.

Manifests live in `models/manifests/*.toml`. Fields are `id`, `provider` (`mock`, `xai`, or
`local`), `model_name`, `capabilities`, `local`, `priority`, `requirements`, and the metrics
`cost_input`, `cost_output`, and `latency`. Unknown metrics stay the string `unknown`.

The router keeps models that declare every requested capability, sorts by priority, and accepts the
first ALLOW decision. The shipped mock manifest uses priority 0, so offline runs select it. The
local manifest sets `ram_known` and `vram_known` to false, so the allocator defers it instead of
inventing hardware numbers.

xAI calls `POST {base}/chat/completions`. A missing `XAI_API_KEY` raises `ProviderError` with code
`configuration` before any HTTP request. Authentication failures are not retried. Timeouts, 429, and
5xx responses retry up to `xai_max_retries`.
