# Tool protocol

A tool has an id, `validate`, and `execute`. The gateway is the only caller of `execute`.

Built-in ids:

- `filesystem.read`, `filesystem.write`, `filesystem.search`, `filesystem.create_directory`
- `terminal.execute`
- `process.list`, `process.start`, `process.stop`
- `system.cpu`, `system.memory`, `system.gpu`, `system.disk`, `system.network`
- `git.status`, `git.diff`, `git.branch`, `git.commit`
- `browser.open`, `browser.search`
- `browser.launch`, `browser.navigate`, `browser.inspect`, `browser.research`, `browser.screenshot`,
  `browser.interact`, `browser.automate`

Filesystem and command paths must resolve inside the workspace. Reads and writes are capped at 1 MB.
`terminal.execute` and `process.start` take an `argv` list and run with `shell=False`.
`browser.open` returns `available: false` when `browser_command` is empty and does not fetch the
URL. The session tools do not accept a shell command or a typed secret. Playwright is not imported.
See `docs/BROWSER.md`.

A result is `ok`, `tool_id`, `output`, optional `error`, `confirmation_required`, and `unavailable`.
