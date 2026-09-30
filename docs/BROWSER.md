# Browser

OMNE keeps four browser layers apart. An agent that can open a URL cannot automate the page, read a
research source, or take a screenshot unless that layer's grant is present.

```text
browser application   the installed program, such as Firefox
browser automation    scripted control of a session
web research          a source lookup that does not drive the browser
web rendering         a screenshot, stored only when rendering is permitted
```

`browser.open` and `browser.search` keep their existing interface. When `browser_command` is empty
they report that browser tooling is unavailable and do not contact the URL. When a command is set,
they run that command as an argument list. They do not open a shell.

## Permissions

| Action     | Tool                 | Grant              | Host effect                                        |
| ---------- | -------------------- | ------------------ | -------------------------------------------------- |
| open       | `browser.open`       | `browser:navigate` | Configured command only                            |
| search     | `browser.search`     | `browser:navigate` | Configured command only                            |
| launch     | `browser.launch`     | `browser:launch`   | Recorded in the mock. Not sent to the host         |
| navigate   | `browser.navigate`   | `browser:session`  | Recorded in the mock. Not sent to the host         |
| inspect    | `browser.inspect`    | `browser:inspect`  | Recorded page fields. No credentials               |
| research   | `browser.research`   | `browser:research` | Fixture source. No page is fetched                 |
| screenshot | `browser.screenshot` | `browser:render`   | Permission is recorded. No image bytes are stored  |
| interact   | `browser.interact`   | `browser:interact` | Yields the session to the user                     |
| automate   | `browser.automate`   | `browser:automate` | A click or a wait, refused while the user holds it |

`browser.launch`, `browser.screenshot`, and `browser.automate` are high risk: confirmation in
development and testing, denied in production. The shipped `browser` agent holds `browser:navigate`
only. The future `browser-worker` agent is the one manifest that holds `browser:automate`.

Automation does not accept a password, a cookie, a token, or typed text. Authentication is a
handoff: `browser.interact` marks the session as controlled by the user, and automation stops until
that session is no longer in user control.

## Engine

Playwright is the documented automation dependency. It is not installed with OMNE, and this revision
does not import it. A host that happens to have the package still has no OMNE adapter, so
automation, live research, and rendering stay unavailable. The mock provider records sessions for
tests and marks them simulated.

`GET /browser` returns availability, the layer list, and any recorded sessions. `POST /browser` is
not a route. `OMNE browser` prints the same status and does not launch a browser.

## Linux

The reader looks for browser desktop entries and matches `/proc/<pid>/cmdline` by program name.
Arguments, including URLs, are not stored. The reader does not start a process.
