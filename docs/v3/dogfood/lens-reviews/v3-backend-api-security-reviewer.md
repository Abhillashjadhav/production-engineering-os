# PD-V3-15 Lens 3 — Backend/API Correctness + Security — CAND-001

## Candidate digest verification
- Manifest (`/tmp/.../scratchpad/dogfood/run/candidate-manifest.json`): CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`, tree_digest `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`, contract_digest `sha256:f01af9c278d32e5c3c953f151662958c8580f109938e44016ac802dc563bad6f`.
- Verified: repo HEAD (`.git/refs/heads/v3/pr16-dogfood`) is exactly `243eddf72005f6f23ed70142053adbd27f7ae3c3` — matches the frozen commit and the task's stated `243eddf72005`. Candidates/CAND-001.json is byte-equal to the manifest. This lens has no shell, so the tree sha256 was not independently recomputed; verification basis is the commit pin. Recorded digest: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`.

## Findings

**F-1 · HIGH · `products/pm-evals-web/backend/src/pm_evals_api/app.py:34,57-64` — size cap enforced after full body receipt, not before parsing.** FastAPI resolves `File(...)` by parsing the whole multipart form before the endpoint runs; Starlette spools parts >1MB to disk temp files. `_read_capped` caps only the read-back of an already fully received, already parsed upload. The comment "bounded before any parsing (T3)" is false at the transport layer; there is no Content-Length precheck or streaming cap middleware. Scenario: a multi-GB multipart body is fully consumed and disk-spooled before the 413 is issued — bandwidth/temp-space exhaustion DoS. `test_api.py:95` (oversize by ~40 bytes) cannot detect this.

**F-2 · HIGH · `products/pm-evals-web/backend/openapi.json:389-402,457-469` vs `app.py:85,94` — committed 422 schema does not match the wire shape.** The schema documents 422 as a bare `ValidationProblem[]`, but `HTTPException(422, detail=problems)` serializes `{"detail": [ValidationProblem...]}` (the tests themselves read `response.json()["detail"]`, `test_api.py:74`). Additionally `_config` (`app.py:94`) returns 422 with a plain-string detail, and FastAPI's native RequestValidationError (missing file, non-integer form value) emits a third shape — the default `HTTPValidationError` was overridden out of the doc. A typed client generated from the committed OpenAPI mis-parses every 422 body. Byte-currency (F-2 note: `test_api.py:157` passes) pins the wrong shape.

**F-3 · MEDIUM · `products/pm-evals-web/backend/pyproject.toml:10` + `Dockerfile:7` — no backend lockfile, no audit gate.** Floor pins only (`>=`); `pip install .` resolves newest-at-build; no hash pinning, no pip-audit evidence. Frontend has `package-lock.json`; backend has nothing. Scenario: two builds of the same frozen commit resolve different pydantic/fastapi versions — "reviewed, tested, and deployed artifact digest-identical" guardrail cannot hold, and F-6's version-dependent behavior is unpinned.

**F-4 · MEDIUM · `products/pm-evals-web/backend/src/pm_evals_compare/compare.py:196` — falsy-zero guardrail bug in the verdict path.** `threshold = candidate_criterion.min_pass_rate or criterion.min_pass_rate`: an explicit candidate `min_pass_rate: 0.0` (valid per `ge=0.0`) is falsy and silently falls through to the baseline's threshold. Scenario: candidate declares 0.0, baseline declares 0.9, candidate rate 0.5 → `guardrail` HOLD contradicting the candidate file's declared threshold. Which run's guardrail governs is also undocumented in the contract (ProductChangeRequest-grade ambiguity).

**F-5 · MEDIUM · `products/pm-evals-web/backend/src/pm_evals_compare/models.py:80` — duplicate JSON object keys accepted silently (parser differential).** `json.loads` keeps the last occurrence; `parse_run` names duplicate ids *within* arrays (models.py:114-132) but two `"traces"`/`"criteria"`/`"results"` keys in one object silently drop data instead of a named refusal. Scenario: a file with two `traces` keys yields PROCEED here but a first-wins parser (or a human reading the file) sees the regressing set — identical bytes, different verdict.

**F-6 · LOW · `products/pm-evals-web/backend/src/pm_evals_compare/models.py:81` — non-standard `NaN`/`Infinity` tokens accepted.** `json.loads` default `allow_nan=True`; no named refusal, no test (grep of tests: zero NaN/Infinity coverage). NaN can land silently in `config`; whether NaN survives pydantic's `ge/le` on `min_pass_rate` is version-dependent (unpinned per F-3) — a NaN threshold makes `rate < threshold` always False, silently disabling a guardrail.

**F-7 · LOW · `products/pm-evals-web/backend/tests/test_api.py:145-154` — residue test does not exercise the disk-spool or error paths.** Fixtures are far below Starlette's 1MB spool threshold and only the 200 path is checked, so the executed evidence never causes a disk write to observe cleanup of. Uploads of 1–5MB (allowed) do hit disk temp files (see F-1), and the 413/422 cycles are unchecked. "Processed in memory, never stored" is proven only for small-file success.

**F-8 · LOW · `products/pm-evals-web/backend/src/pm_evals_api/app.py:162` — `/api/report` bytes are not identical for identical inputs.** `datetime.now` is embedded into the artifact ("Generated at:" in markdown body, `generated_at` in JSON). PD-V3-07 permits labeled timestamp fields and the engine renders deterministically without one (`test_compare.py:248-257`), but contract GATE-2/GATE-4 says "identical inputs produce identical verdicts **and reports**" — no test asserts report identity modulo the timestamp. Reconciling GATE-4 wording with the timestamp is a ProductChangeRequest flag, not a code fix.

## Verdicts per audited guarantee

| Guarantee | Verdict | Evidence |
|---|---|---|
| API-1..3 documented + committed schema byte-current | PASS | openapi.json covers all three; `test_api.py:157-167` executed byte-diff |
| Response shapes match documented contract | FAIL | F-2: three undocumented 422 wire shapes vs the committed `ValidationProblem[]` schema |
| Error mapping locked (malformed→named 422, incompatible→200 HOLD) | PASS (behavioral) | `test_api.py:70-92` executed; shape fidelity failure tracked under F-2 |
| Size caps before parsing | FAIL | F-1: cap applied post-receipt, post-multipart-parse |
| Parser differentials → named refusals | FAIL | Encodings/recursion handled and tested (`models.py:81`, `test_api.py:170-178`); duplicates and NaN/Infinity silent (F-5, F-6) |
| Hostile filenames never in headers/paths | PASS | Filenames never dereferenced; fixed `Content-Disposition`; executed `test_api.py:102-110` |
| Determinism (PD-V3-07), verdict path | PASS | No clock/randomness in `compare.py`; sorted iteration; `test_compare.py:248-265`, `test_api.py:139-142` — with F-4 correctness caveat and F-8 report-bytes caveat vs GATE-4 |
| No persistence of uploads | NOT_PROVEN | Residue test executed but blind to the spool threshold and error paths (F-1, F-7) |
| Zero egress from backend | NOT_PROVEN | Grep of `src/` shows no outbound client imports and runtime deps contain no HTTP client, but there is no executed zero-egress test — untested guarantee per charter |
| No upload content cached/logged | PASS | 422 details echo ids to the uploader only; JSONDecodeError messages carry positions, not content; no logging of bodies |
| Dependency risk (lockfile-resolved, audited) | FAIL | F-3: no backend lockfile, no audit gate executed |

Digest verified and recorded: `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb` (CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`, commit-pin verified; tree hash not independently recomputed — no shell in this lens).
