# feat: TaskFlow MVP (run-20260712-184538-e77816)

Automated build of TaskFlow from the approved MVP specification.

Plan: 6 tasks; APIs: GET /health, POST /tasks, GET /tasks, GET /tasks/{id}, PATCH /tasks/{id}, DELETE /tasks/{id}.
Requirement coverage is enforced by the merge gate.

## Commits
- feat: T-006 Server entrypoint, configuration, and product README
- feat: T-005 HTTP API handlers (routing, request validation, JSON errors)
- feat: T-004 Bearer-token auth (env-injected token, constant-time compare)
- feat: T-003 Storage layer for Task (SQLite, parameterized queries)
- test: T-002 add generated test suite (before implementation)
- chore: T-001 scaffold workspace

## Diff
```
README.md                     |  37 +++++++++-
 app/__init__.py               |   1 +
 app/api.py                    | 166 ++++++++++++++++++++++++++++++++++++++++++
 app/auth.py                   |  30 ++++++++
 app/server.py                 |  49 +++++++++++++
 app/storage.py                |  89 ++++++++++++++++++++++
 tests/__init__.py             |   0
 tests/integration/__init__.py |   0
 tests/integration/test_api.py | 143 ++++++++++++++++++++++++++++++++++++
 tests/unit/__init__.py        |   0
 tests/unit/test_auth.py       |  47 ++++++++++++
 tests/unit/test_storage.py    |  79 ++++++++++++++++++++
 12 files changed, 640 insertions(+), 1 deletion(-)
```
