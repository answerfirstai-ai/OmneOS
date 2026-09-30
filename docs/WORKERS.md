# Workers

An agent is a capability definition. A worker is a runtime instance that executes one piece of work
for that definition.

```text
agent     identity, tools, permissions, resources, max_workers
worker    one in-memory instance of an agent
```

A worker record holds an id, the parent agent, the task, capabilities, model, tools, permissions,
the declared resource allocation, a short context, the lifecycle, and a trace id. The record is not
an operating-system process. A hundred workers are a hundred records in the pool.

## Lifecycle

```text
DISCOVERED → AVAILABLE → SPAWNED → RUNNING
RUNNING → IDLE | PAUSED | FAILED | TERMINATED
IDLE → SPAWNED
PAUSED → RUNNING | IDLE
FAILED → TERMINATED
```

`worker.discovered`, `worker.available`, `worker.spawned`, `worker.started`, `worker.reused`,
`worker.resumed`, `worker.idle`, `worker.paused`, `worker.completed`, `worker.cancelled`,
`worker.failed`, and `worker.terminated` are the events. The payload carries the lifecycle. It does
not carry a command line.

IDLE and PAUSED workers for the same agent are reused. A failed worker holds its slot until it is
terminated. An on-demand agent terminates idle workers when the task finishes. A persistent agent
keeps the idle worker for the next task.

## Scheduling

`admit_worker` denies a start at `max_workers`. It denies a request larger than the memory budget.
It waits when other workers already hold the remaining memory, and when a measured CPU percent is at
least 95. Unknown CPU does not count as free or busy capacity. The runtime pool uses an 8192 MB
budget. A new worker also reserves its manifest on the shared resource manager. Reuse keeps that
hold, and termination releases it. The task scheduler asks the pool before it reserves a slot,
including that CPU reading. See `docs/protocols/COMPUTE.md`.

The shell lists agent definitions and runtime workers separately. A definition is not a worker, and
a paused or stopped worker is not shown as active.
