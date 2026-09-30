# Event protocol

Events are JSON objects with `id`, `type`, `timestamp`, and optional `task_id`, `agent_id`,
`model_id`, `tool_id`, and `payload`.

Emitted types:

- `task.started`, `task.completed`, `task.failed`, `task.recovered`, `task.cancelled`
- `tool.requested`, `tool.executed`, `tool.denied`, `tool.failed`
- `permission.requested`, `permission.granted`, `permission.denied`
- `agent.registered`, `agent.started`, `agent.completed`, `agent.failed`, `agent.unloaded`
- `agent.message`
- `model.loading`, `model.loaded`, `model.running`, `model.idle`, `model.unloading`,
  `model.unloaded`, `model.failed`, `model.cancelled`

`model.loaded` means a runtime reported the model resident. OMNE does not download weights to emit
it. A task that never calls load, including an ordinary file write, does not emit `model.loaded`.

`GET /events?after=<id>` returns events after that id. `list_events(limit=n)` returns the tail. The
bus keeps the latest 1000 events in memory and appends them to `events.jsonl` under the data
directory. The append handle stays open and is flushed on each publish.
