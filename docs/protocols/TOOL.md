# Tool protocol

A tool has an id, `validate`, and `execute`. The gateway is the only caller of `execute`.

Built-in ids:

- `filesystem.read`, `filesystem.write`, `filesystem.search`, `filesystem.create_directory`
- `terminal.execute`
- `process.list`, `process.start`, `process.stop`, `process.restart`, `process.command`
- `system.cpu`, `system.memory`, `system.gpu`, `system.disk`, `system.network`
- `git.status`, `git.diff`, `git.branch`, `git.commit`
- `browser.open`, `browser.search`
- `browser.launch`, `browser.navigate`, `browser.inspect`, `browser.research`, `browser.screenshot`,
  `browser.interact`, `browser.automate`

Filesystem and command paths must resolve inside the workspace. Reads and writes are capped at 1 MB.
`terminal.execute` takes an `argv` list and runs with `shell=False`. `process.start` takes an `argv`
list and records it through the process service. It does not open a shell. The Linux provider does
not spawn or signal a process. Command lines stay off `process.list` unless `process.command` is
granted. See `docs/PROCESSES.md`. `browser.open` returns `available: false` when `browser_command`
is empty and does not fetch the URL. The session tools do not accept a shell command or a typed
secret. Playwright is not imported. See `docs/BROWSER.md`.

A result is `ok`, `tool_id`, `output`, optional `error`, `confirmation_required`, and `unavailable`.
