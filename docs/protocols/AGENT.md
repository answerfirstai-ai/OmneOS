# Agent protocol

A manifest is TOML with `id`, `name`, `version`, `description`, `capabilities`, `tools`,
`permissions`, `resources`, and `lifecycle`. Persistent agents must shut down `never`. Other agents
shut down `after_task`. Unknown tool ids are rejected when the loader is given the registry.

Shipped agents:

| id             | Capabilities                               | Tools                                |
| -------------- | ------------------------------------------ | ------------------------------------ |
| system         | system and process inspection              | system telemetry and `process.list`  |
| coding         | development, analysis, testing, debugging  | filesystem, terminal, process, git   |
| research       | source collection, summarization, research | filesystem read and search           |
| browser        | navigation                                 | `browser.open` and `browser.search`  |
| browser-worker | automation, research, rendering, handoff   | session tools, each behind its grant |

The system agent can list processes. The coding agent can also start and stop one it owns. Neither
manifest holds `process:command` or `process:restart`. See `docs/PROCESSES.md`.

An agent manifest is a definition. A worker is a runtime instance of that definition, with its own
lifecycle. See `docs/WORKERS.md`.

Lifecycle edges are enforced. Illegal edges raise `InvalidAgentTransition`. Agents exchange
`AgentMessage` values, which also publish `agent.message`.
