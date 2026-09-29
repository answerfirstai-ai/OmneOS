# Roadmap

The implementation follows the JARVIS OS master specification. A phase starts only after the
previous phase meets its acceptance criteria.

## Phase 1 — Foundation

Implemented in this revision.

- Python package `core` with configuration, logging, and a local health service.
- TypeScript shell that displays core health.
- Formatting, linting, type checks, tests, and a CI workflow.
- Development, testing, and production configuration files.

## Later phases

These phases are not implemented:

| Phase | Subject                                                                      |
| ----- | ---------------------------------------------------------------------------- |
| 2     | Task model, state transitions, events, and a minimal execution path          |
| 3     | Filesystem, terminal, process, system, and Git tools                         |
| 4     | Permission policies, evaluation, confirmation, and audit                     |
| 5     | Model provider interface, mock provider, xAI provider, registry, and routing |
| 6     | Agent manifests, registry, lifecycle, and initial agents                     |
| 7     | Scoped memory and retrieval                                                  |
| 8     | Compute telemetry, allocation, and model-cache metadata                      |
| 9     | Multi-agent orchestration and recovery                                       |
| 10    | Desktop shell, launcher, search, and monitors                                |
| 11    | Character renderer driven by core events                                     |
| 12    | Voice providers                                                              |
| 13    | Linux service integration                                                    |
| 14    | Reproducible OS image                                                        |
| 15    | Virtual machine acceptance                                                   |
| 16    | Physical hardware, only with explicit approval                               |

Protocol documents for agents, tools, models, compute, memory, and events will be added with the
phase that introduces each protocol.
