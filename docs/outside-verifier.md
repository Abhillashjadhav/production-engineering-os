# Outside-verifier boundary (PE8)

This local implementation measures the approved structured Given/When/Then
outcome at one registered action's **public JSON response**. It does not prove a
private Python return value, internal implementation, absence of side effects,
general correctness, or hidden inputs.

The trusted supervisor keeps the approved contract, exact compiled plan,
template action mapping/context, assertion operators, evidence ledger and
verdict. For each required criterion it checks Given against trusted context,
selects the registered target and literal arguments, runs the frozen candidate
snapshot through Bubblewrap, admits one bounded UTF-8 JSON value, then applies
the original Then predicates outside candidate Python. A missing, malformed,
duplicate-key, non-finite, over-range, oversized or nonzero-exit response is a
verification error, not an assertion RED or PASS. Candidate stdout claiming a
verdict is just candidate data. The supported `matches` operator keeps its
approved Python-regex semantics but runs under a trusted child-process watchdog
using the existing 10-second action timeout; a timeout is a verifier error,
never an assertion result. Each action and regex child receives at most the
remaining 120-second per-verification budget, checked between predicates and
criteria; host filesystem bookkeeping is not preempted mid-operation. The
aggregate observation limit is 8 MB. These are execution-resource bounds,
not product-quality thresholds.

Each attempt records supervisor-computed observations and response blobs bound
to the contract, plan, template and candidate manifest. New release records use
`external-json-response-v1`; inspection does not label older pytest-based
records independently verified. Evidence-integrity PASS and product-verification
PASS remain separate claims. Human release authorization is still required.

The compiler still accepts `human_test`, `satisfied_by_template`, and `measure`
for compatibility. The runtime refuses them with criterion-specific
`UNSUPPORTED_VERIFICATION_MODE` before provider/candidate execution, including
mixed plans. A trusted human-test observation adapter or a protected
measurement collector would require a future separate contract.

**Current limit:** Bubblewrap contains generated candidate code, but the outer
generic provider command runs as the invoking host user. It can write any
verifier, contract or ledger path writable by that user. This implementation
does not satisfy full coding-agent write isolation. The run records
`UNVERIFIED_GENERIC_COMMAND` rather than claiming that assurance. Enforcing it
requires an operator-controlled verifier/approval image or identity, supervisor-
only ledger write authority, and confinement of the *entire* provider process
tree before adapter startup. No host permission, credential or namespace setup
is performed by this code change. A correct candidate response is retained as
`candidate_response_verified` with its manifest and supervisor observations,
then the generic-provider run terminates `HALTED` with
`PROVIDER_WRITE_ISOLATION_UNVERIFIED`. It emits no `release_ready` event and
returns no `RELEASE_READY` RunResult. All release consumers therefore refuse
this candidate-only result rather than relying on an optional presentation
field. The separate static support-package sealer and offline recorded-tool
fixture use their own evidence contracts and do not attest generic Coder
noninterference.

Mocked sandbox tests check parser, orchestration and verdict logic only. A
supported-host proof additionally needs the exact final source on Linux with
working Bubblewrap, user/PID/mount namespaces and `prlimit`, under Python 3.11
and 3.12, with selected real candidate tamper controls. Until those run, report
`SUPPORTED_HOST_PROOF_PENDING`. No unsandboxed fallback is permitted.

The optional [offline whole-provider launcher](provider-isolation.md) is a
separate next step toward the broader agent-noninterference goal. It cannot
turn the current candidate-only result into a release verdict.
