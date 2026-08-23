# Production Engineering OS (`pmpe`)

> **ALPHA — evidence status:** the frozen bare-bones core has passed deterministic tests and a scripted-provider fixture. No PM Agent OS contract has yet completed the path with a real model provider. The repository therefore does **not** yet claim arbitrary product generation, production readiness, deployment, or platform validation.

An open-source, local-first reference implementation that compiles a machine-checkable product contract into executable assertions, drives one bounded Coder through a command adapter, executes generated candidate code inside an OS sandbox, and records a tamper-evident evidence chain.

## What is proven today

| Capability | Evidence status |
|---|---|
| Deterministic contract compilation and compile-time rejection | Proven by [exact-head compiler tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/e25c605fb043a64d019938ee8e67c1518337e0a6/tests/unit/test_acceptance_compiler.py) and [CI #842](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32619855405) |
| Meaningful-RED baseline, bounded repair, and six-state engine | Proven by [exact-head E1/eval tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/e25c605fb043a64d019938ee8e67c1518337e0a6/tests/e2e/test_barebones_e1.py) and [CI #842](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32619855405) |
| Hash-chained events and content-addressed evidence blobs | Proven by [exact-head ledger tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/e25c605fb043a64d019938ee8e67c1518337e0a6/tests/unit/test_evidence_ledger.py) and [CI #842](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32619855405) |
| Candidate execution with Bubblewrap, no network, and bounded resources | Proven by [planted isolation tests](https://github.com/Abhillashjadhav/production-engineering-os/blob/e25c605fb043a64d019938ee8e67c1518337e0a6/tests/unit/test_candidate_sandbox.py) in [Linux CI #842](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32619855405) |
| End-to-end `RELEASE_READY` engine path | Proven by the [scripted exact-head E1 fixture](https://github.com/Abhillashjadhav/production-engineering-os/blob/e25c605fb043a64d019938ee8e67c1518337e0a6/tests/e2e/test_barebones_e1.py) in [CI #842](https://github.com/Abhillashjadhav/production-engineering-os/actions/runs/32619855405) |
| Canonical PMOS contract accepted by the grammar | **Not yet proven** |
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

The Coder is the only mandatory LLM worker. A command implementing the `ModelProvider` JSON protocol is the only external adapter. That provider command currently runs as the invoking host user with the host process environment and filesystem permissions; it is **not** inside the Bubblewrap candidate sandbox. Treat the provider command as trusted. The core does not deploy, mutate GitHub, or make the release decision.

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
  --expected-approver fixture-human \\
  --provider-command "python examples/barebones/e1-provider.py"
```

The example provider returns scripted responses. It proves compiler-to-engine plumbing; it does not prove that an LLM can build the requested software.

For a real-model run, use the documented [OpenAI Responses API reference provider](docs/real-model-provider.md). Its implementation and unit tests prove the adapter boundary only; no live PMOS-to-real-model run is claimed until its complete evidence bundle is published.

A provider receives one JSON object on standard input:

```json
{"purpose": "code|advisory_review", "request": {}}
```

The contract must contain `contract_status: APPROVED` and `approved_by`; the CLI requires an exact `--expected-approver` match before invoking the provider. The provider must return one UTF-8 JSON object containing the same `request_digest`. Do not record provider credentials in contracts, commands, candidate workspaces, or evidence.

## Current evidence gap

The canonical PMOS fixture contains prose that resembles Given/When/Then but does not identify a registered action or typed output paths. The compiler correctly refuses to guess. A real E1 begins only when PMOS emits the structured grammar or binds a requirement to an admitted human-authored test.

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
