# Memory protocol

Records have `id`, `scope`, `scope_key`, `content`, `metadata`, and `created_at`.

Scopes are `conversation`, `task`, `project`, `long_term`, and `system`. `AccessGrant.require`
rejects a scope the caller does not hold, including reads. Queries use a bounded `LIKE` match with
`%`, `_`, and `\` escaped, ordered by `created_at` then `id`. The store does not place the full
database into a model prompt.
