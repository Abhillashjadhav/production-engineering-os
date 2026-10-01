# W2 owner decision — source-only admission

- **Question (asked 2026-09-25, from `reviews/r4-architecture-20260925/DECISION_REQUIRED.md`):**
  To pass the unchanged architecture scanner without weakening stale-bytecode
  protection, should gated runs be required to start in a fresh source-only Python
  process? Ordinary-interpreter library calls and tests that use process gates would
  be refused and must use that startup.
- **Options offered:** approve source-only start / keep the guard and leave the
  architecture check failing / drop the registry scan and accept a narrow gap.
- **Owner answer (Abhillash Jadhav, 2026-09-25 18:29 IST):** "Approve source-only start".
- **Scope of approval:** this execution boundary only. It does not approve a
  product contract, release, merge, model spending or deployment.

## Invariant implemented

A gated run is admitted only when the interpreter:

1. was started with bytecode writes disabled (`sys.flags.dont_write_bytecode`), and
   they are still disabled;
2. was started with an absolute cache prefix (`-X pycache_prefix` or `PYTHONPYCACHEPREFIX`)
   and `sys.pycache_prefix` still equals it;
3. has an empty prefix directory.

Under those conditions every module in the process came from source: the import
system could only look for bytecode in an empty directory, and nothing was written.
This replaces the `sys.modules` scan. The local `.pyc`/`.pyo` scan, the future-cache
scan at the current prefix (optimizations "", 1, 2) and the engine's own
`__cached__` check are kept.

Canonical identity uses the class body's own functions: their `__globals__` name the
module that actually compiled them, which a relabelled `__module__` cannot change.
The claimed qualname must resolve to the same class object in that namespace.

## Residual limits (unchanged trust model)

- Code already running inside the admitted process can still monkeypatch the guard.
  The previous registry scan had the same limit.
- An external process that writes and then deletes bytecode inside the private prefix
  during startup is outside this check.
- The bytecode-injection and evidence-forgery adversarial rechecks recorded as
  UNVERIFIED in `reviews/r4-architecture-20260925/static-red.json` were not rerun.
