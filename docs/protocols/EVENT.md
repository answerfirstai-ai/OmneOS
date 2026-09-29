# Event protocol

Events are JSON objects with `id`, `type`, `timestamp`, and optional `task_id`, `agent_id`,
`model_id`, `tool_id`, and `payload`.

Emitted types:

- `task.started`, `task.completed`, `task.failed`, `task.recovered`, `task.cancelled`
- `tool.requested`, `tool.executed`, `tool.denied`, `tool.failed`
- `permission.requested`, `permission.granted`, `permission.denied`
- `agent.registered`, `agent.started`, `agent.completed`, `agent.failed`, `agent.unloaded`
- `agent.message`

`model.loaded` is not emitted. No model weights are loaded.

`GET /events?after=<id>` returns events after that id. The bus keeps the latest 1000 events in
memory and appends them to `events.jsonl` under the data directory.
