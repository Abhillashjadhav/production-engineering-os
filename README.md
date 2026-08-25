# Production Engineering OS (`pmpe`)

> **ALPHA — evidence status:** the frozen bare-bones core has passed deterministic tests, a scripted-provider fixture, and that complete engine fixture through real Bubblewrap on Linux. No PM Agent OS contract has yet completed the path with a real model provider. The repository therefore does **not** yet claim arbitrary product generation, production readiness, deployment, or platform validation.

An open-source, local-first reference implementation that compiles a machine-checkable product contract into executable assertions, drives one bounded Coder through a command adapter, executes generated candidate code inside an OS sandbox, and records a tamper-evident evidence chain.

## What is proven today

| Capability | Evidence status |
|---|---|
| Deterministic contract compilation and compile-time rejection | Proven by [exact-head compiler tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/unit/test_acceptance_compiler.py) in [exact-head CI #32654697877](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32654697877) |
| Meaningful-RED baseline, bounded repair, and six-state engine | Proven by the [exact-head E1 fixture](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/e2e/test_barebones_e1.py) and [planted eval suite](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/e2e/test_barebones_evals.py) in [exact-head CI #32654697877](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32654697877) |
| Hash-chained events and content-addressed evidence blobs | Proven by [exact-head ledger tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/unit/test_evidence_ledger.py) in [exact-head CI #32654697877](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32654697877) |
| Candidate execution with real Bubblewrap, no network, a read-only host view, bounded resources, symlink containment, and fail-closed composition | Proven by the [exact-head isolation tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/unit/test_candidate_sandbox.py) in the dedicated Linux `candidate-isolation` matrix of [exact-head CI #32654697877](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32654697877) |
| End-to-end scripted-provider `RELEASE_READY` engine path through real Bubblewrap | Proven by the [exact-head E1 fixture](https://github.com/Abhillashjadhav/production-engineering-os/blob/8c096b18839d8265e0fb3cb6fd9660bb4dca9cd7/tests/e2e/test_barebones_e1.py), with the local sandbox fixture disabled under `PMPE_TEST_REAL_SANDBOX=true`, in [exact-head CI #32654697877](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32654697877) |
| Canonical PMOS contract and digest-bound approval receipt accepted by the boundary | Proven by the [PMOS executable compatibility gate](https://github.com/Abhillashjadhav/PM-agent-OS/blob/5fa7af8207143194eb242f2edd9f7edfca8bb969/tests/decision-to-contract/validate_contract.py), including a planted post-approval tampering rejection |
| Product built with a real model provider | **Not yet proven** |
| Repeated real-provider behavioural drift evidence | **Not yet proven** |
| Reuse across multiple distinct product contracts | **Not yet proven** |
| macOS or Windows native execution | **Not supported** |
| Cloud deployment, GitHub mutation, or automatic release | **Out of scope** |

The current classification is **reference implementation**. A reusable product or platform remains a hypothesis until multiple real contracts complete the path with a real provider and recorded evidence.

## Frozen core

```text
PMOS contract
  → deterministic compile + coverage
  → meaningful baseline RED
  → one bounded Coder
  → deterministic verification + local security
  → RELEASE_READY or HALTED
  → human release decision
```

The engine has six states: `VALIDATED`, `BUILDING`, `VERIFYING`, `RELEASE_READY`, `HALTED`, and `STOPPED`.

The Coder is the only mandatory LLM worker. A command implementing the `ModelProvider` JSON protocol is the only external adapter. That provider command currently runs as the invoking host user with the host process environment and filesystem permissions; it is **not** inside the Bubblewrap candidate sandbox. Treat the provider command as trusted. The core does not deploy, mutate GitHub, or make the release decision. When the Codex CLI adapter is selected, one bounded PEOS call contains an agentic `codex exec` loop whose internal turns are not individually visible to PEOS.

Evidence is stored as plain files:

```text
.pmpe/runs/<run-id>/events.jsonl
.pmpe/blobs/<sha256>
```

Read the [acceptance grammar](docs/acceptance-criteria-grammar.md) and [deletion inventory](docs/barebones-deletion-inventory.md) before extending the engine.

## Requirements

- Python 3.11 or 3.12
- Linux
- Bubblewrap (`bwrap`)
- `prlimit` from util-linux
- User namespaces permitted by the host
- A command-backed model provider for any real-model run

Bubblewrap shares the host kernel. The current boundary is designed to contain defective generated code on a local developer machine; it is not a multi-tenant security boundary for targeted hostile workloads.

On Ubuntu 24.04, AppArmor may block unprivileged user namespaces. The CI allowance is:

```text
abi <abi/4.0>,
include <tunables/global>
/usr/bin/bwrap flags=(unconfined) {
  userns,
}
```

Install that as an AppArmor profile for `/usr/bin/bwrap` only if your host policy permits it. On macOS or Windows, run the project inside a Linux VM or container with the required namespace capabilities.

## Install and run the deterministic fixture

On Debian or Ubuntu, install both required OS tools first:

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap util-linux
```

Then install and run PMPE:

```bash
git clone https://github.com/Abhillashjadhav/production-engineering-os.git
cd production-engineering-os
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pmpe barebones examples/barebones/e1-contract.json \
  --workspace /tmp/pmpe-e1-candidate \
  --run-id e1 \
  --repository-root /tmp/pmpe-e1-evidence \
  --approval-receipt examples/barebones/e1-approval-receipt.json \
  --expected-approver fixture-human \
  --provider-command "python examples/barebones/e1-provider.py"
```

The example provider returns scripted responses. It proves compiler-to-engine plumbing; it does not prove that an LLM can build the requested software.

For a real-model run, use one of the documented [reference providers](docs/real-model-provider.md): the Responses API adapter or the Codex CLI adapter with saved ChatGPT subscription authentication. Their implementation and unit tests prove the adapter boundary only; no live PMOS-to-real-model run is claimed until its complete evidence bundle is published.

A provider receives one JSON object on standard input:

```json
{"purpose": "code|advisory_review", "request": {}}
```

The contract must contain `contract_status: APPROVED` and `approved_by`; the CLI requires an exact `--expected-approver` match before invoking the provider. The provider must return one UTF-8 JSON object containing the same `request_digest`. Do not record provider credentials in contracts, commands, candidate workspaces, or evidence.

The Codex CLI path is deliberately explicit about its boundaries: it requires a host
`CODEX_HOME` authenticated with ChatGPT, strips API-key variables, and enforces ChatGPT
mode again on the command line. Its ephemeral read-only sandbox protects the provider
run; the separate Bubblewrap sandbox protects candidate execution. The prompt still
transits OpenAI. Subscription runs record pricing as not applicable per run rather than
claiming a zero-dollar API cost.

## Current evidence gap

PMOS now publishes a compiler-shaped health contract plus an approval receipt bound to the exact contract digest; its pinned compatibility gate verifies the receipt, accepts the valid contract, rejects a post-approval edit, and rejects prose-only criteria. This proves the PMOS-to-PEOS handoff shape. It does not prove live-model contract-authoring reliability or a real provider build. A real E1 begins when that approved boundary is exercised with a configured provider and its complete evidence bundle is published.

The next promotion gate is one real PMOS-authored contract reaching `RELEASE_READY` through a real provider with:

- zero human implementation edits;
- the ratio of structured criteria (Forms A+B) to human tests (Form C);
- attempts, calls, tokens, estimated cost, and wall time;
- a complete valid evidence chain;
- an honest record of failures as well as success.

## Historical and adjacent surfaces

This repository still contains historical commands and packages for `demo`, `eng start`, personal workflows, guided mode, full-product workflows, repository/deployment adapters, and a larger multi-agent lifecycle. They are **legacy surfaces being classified for deletion or separation**. They are not dependencies of the frozen bare-bones core and are not evidence that the alpha can generate or deploy arbitrary products.

PM Agent OS is a separate product and has its own repository: [Abhillashjadhav/PM-agent-OS](https://github.com/Abhillashjadhav/PM-agent-OS). Its skills and product-reasoning claims should be evaluated independently from the `pmpe` runtime.

## Review and claim policy

Repository changes use automated review plus maintainer self-review. That record is useful engineering evidence, but it is not represented as independent human peer review.

No public capability claim should be added without a linked recorded run that demonstrates it. Scripted fixtures may support plumbing claims only. Security claims require implementation inspection and planted-failure tests.

## Non-goals for this alpha

- Hosted or multi-tenant service
- Automatic deployment or release
- Web UI
- Additional workers, lifecycle states, templates, adapters, operators, or actions without a failing real contract
- Plugin or extension marketplace
- Native macOS or Windows sandboxing

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New runtime surface must be justified by a failing real contract or eval and preserve fail-closed behavior.

## License

MIT.

---

Built by [Abhillash Jadhav](https://github.com/Abhillashjadhav).
