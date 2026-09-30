# Applications

OMNE treats an installed desktop application as an object. Opening one is a lookup, not a shell
command.

```text
“Open Firefox”
    intent application.open
    → lookup by name or id
    → permission application:launch
    → launch the registered program, or refuse on the host
    → observe a matching process
    → observe a matching window
    → report
```

Core depends on `omne.applications`. The Linux provider reads desktop files. Tests and non-Linux
hosts use a mock catalog that includes Firefox and Files. There is no package manager in this
revision.

## What an application contains

| Field           | Meaning                                                              |
| --------------- | -------------------------------------------------------------------- |
| `id`            | The desktop file name without `.desktop`                             |
| `name`          | The `Name` key                                                       |
| `desktop_entry` | The file name, not a copy of an `Exec` line                          |
| `executable`    | The program named by `Exec`, or null when that line is not a program |
| `icon`          | The `Icon` key                                                       |
| `categories`    | The `Categories` list                                                |
| `permissions`   | `application:launch` when the entry can be launched                  |
| `processes`     | Observed pid and program name. Arguments are not stored              |
| `windows`       | Observed id, title, application id, and focus                        |
| `state`         | `installed`, `running`, `focused`, or `hidden`                       |

`commanded` stays false. A desktop `Exec` that uses a shell, a pipe, or another shell metacharacter
is stored with `launchable` false and is not started.

## Actions

| Action  | Permission           | Host effect                                |
| ------- | -------------------- | ------------------------------------------ |
| search  | none                 | Read                                       |
| inspect | none                 | Read                                       |
| launch  | `application:launch` | Recorded in the mock. Not sent to the host |
| focus   | `application:focus`  | Recorded in the mock. Not sent to the host |
| close   | `application:close`  | Recorded in the mock. Not sent to the host |

`application.launch` and `application.close` are high risk: confirmation in development and testing,
denied in production. No agent manifest holds these grants. The tool arguments are a name or an id.
`argv`, `command`, and `shell` are rejected.

`GET /applications` returns the catalog. `POST /applications` is not a route. `OMNE applications`
prints the catalog and does not launch anything.

The shell launcher lists visible applications. Choosing one fills the command field with
`Open <name>`. Sending that objective follows the same intent and permission path.

## Linux

The reader looks in `usr/share/applications` and `usr/local/share/applications`. It matches
`/proc/<pid>/cmdline` by the program name only. On a fixture root it can also read
`run/omne/windows.json`. A live host is not given that default path. The reader does not spawn a
process and does not install a package.
