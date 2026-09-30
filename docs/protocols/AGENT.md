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

Lifecycle edges are enforced. Illegal edges raise `InvalidAgentTransition`. Agents exchange
`AgentMessage` values, which also publish `agent.message`.
