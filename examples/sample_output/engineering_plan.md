# Engineering plan

| Task | Title | Component | Covers | Depends on | Size |
|---|---|---|---|---|---|
| T-001 | Scaffold workspace (package layout, gitignore, README stub) | project | — | — | S |
| T-002 | Generated test suite (written before implementation) | tests | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007 | T-001 | M |
| T-003 | Storage layer for Task (SQLite, parameterized queries) | storage | FR-002, FR-003, FR-004, FR-005, FR-006 | T-001 | L |
| T-004 | Bearer-token auth (env-injected token, constant-time compare) | auth | FR-001 | T-001 | M |
| T-005 | HTTP API handlers (routing, request validation, JSON errors) | api | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007 | T-003, T-004 | L |
| T-006 | Server entrypoint, configuration, and product README | server | FR-007 | T-005 | S |

Order: T-001 → T-002 → T-003 → T-004 → T-005 → T-006

APIs: GET /health, POST /tasks, GET /tasks, GET /tasks/{id}, PATCH /tasks/{id}, DELETE /tasks/{id}

Risks:
- A single static token, if leaked, exposes all data until rotated
- Single-process deployment has no high-availability story
- Auth is security-sensitive: token handling reviewed by the security gate and flagged medium-risk by policy
