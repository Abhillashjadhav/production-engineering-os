# Production Engineering OS (`pmpe`)

> **ALPHA — evidence status:** one tiny approved PM Agent OS contract has completed the frozen bare-bones path with a ChatGPT-authenticated Codex CLI provider and reached `RELEASE_READY`; its [complete evidence chain is published](docs/evidence/e1-real-provider-20260826/README.md). This proves that one bounded run, not repeatability, materially different contracts, arbitrary product generation, production readiness, deployment, or platform validation.

An open-source, local-first reference implementation that compiles a machine-checkable product contract into executable assertions, drives one bounded Coder through a command adapter, executes generated candidate code inside an OS sandbox, and records a tamper-evident evidence chain.

## What is proven today

| Capability | Evidence status |
|---|---|
| Deterministic contract compilation and compile-time rejection | Proven by the [compiler tests](tests/unit/test_acceptance_compiler.py) enforced in [main CI](https://github.com/Abhillashjadhav/production-engineering-os/actions/workflows/ci.yml?query=branch%3Amain) |
| Meaningful-RED baseline, bounded repair, and six-state engine | Proven by the [E1 fixture](tests/e2e/test_barebones_e1.py) and [planted eval suite](tests/e2e/test_barebones_evals.py) enforced in [main CI](https://github.com/Abhillashjadhav/production-engineering-os/actions/workflows/ci.yml?query=branch%3Amain) |
| Hash-chained events and content-addressed evidence blobs | Proven by the [ledger tests](tests/unit/test_evidence_ledger.py) enforced in [main CI](https://github.com/Abhillashjadhav/production-engineering-os/actions/workflows/ci.yml?query=branch%3Amain) |
| Candidate execution with real Bubblewrap, no network, a read-only host view, bounded resources, symlink containment, and fail-closed composition | Proven by the [isolation tests](tests/unit/test_candidate_sandbox.py) in the dedicated Linux `candidate-isolation` matrix of [main CI](https://github.com/Abhillashjadhav/production-engineering-os/actions/workflows/ci.yml?query=branch%3Amain) |
| End-to-end scripted-provider `RELEASE_READY` engine path through real Bubblewrap | Proven by the [E1 fixture](tests/e2e/test_barebones_e1.py), with the local sandbox fixture disabled under `PMPE_TEST_REAL_SANDBOX=true`, in [main CI](https://github.com/Abhillashjadhav/production-engineering-os/actions/workflows/ci.yml?query=branch%3Amain) |
| Canonical PMOS contract and digest-bound approval receipt accepted by the boundary | Proven by the [PMOS executable compatibility gate](https://github.com/Abhillashjadhav/PM-agent-OS/blob/5fa7af8207143194eb242f2edd9f7edfca8bb969/tests/decision-to-contract/validate_contract.py), including a planted post-approval tampering rejection |
| One tiny approved contract built with a real model provider | [Proven once by the published E1 run](docs/evidence/e1-real-provider-20260826/README.md) |
| Customer-support portable package assembly with recorded/memory/fixture reference adapters | Implemented and verified by the package contract, manifest, tamper, negative-capability, and local HTTP journey tests; this proves no live model or vendor connector |
| Repeated real-provider behavioural drift evidence | **Not yet proven** |
| Reuse across multiple distinct product contracts | **Not yet proven** |
| macOS or Windows native execution | **Not supported** |
| Cloud deployment, GitHub mutation, or automatic release | **Out of scope** |

The current classification is **reference implementation**. A reusable product or platform remains a hypothesis until multiple real contracts complete the path with a real provider and recorded evidence.

The bounded #146 evidence runner is available as
`python examples/barebones/run_real_behavior_drift_eval.py`. Its existence proves the
experiment is reproducible. The launcher imports PMPE from that exact checkout, even when
a different installation is present; this table remains unchanged until the resulting real
ledgers are published and independently verified.

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

pmpe barebones run examples/barebones/e1-contract.json \
  --workspace /tmp/pmpe-e1-candidate \
  --run-id e1 \
  --repository-root /tmp/pmpe-e1-evidence \
  --approval-receipt examples/barebones/e1-approval-receipt.json \
  --expected-approver fixture-human \
  --provider-command "python examples/barebones/e1-provider.py"
```

The default product journey is intentionally small:

```bash
pmpe barebones compile examples/barebones/e1-contract.json --repository-root .
pmpe barebones status e1 --repository-root /tmp/pmpe-e1-evidence
pmpe barebones evidence e1 --repository-root /tmp/pmpe-e1-evidence
pmpe barebones inspect e1 \
  --repository-root /tmp/pmpe-e1-evidence \
  --workspace /tmp/pmpe-e1-candidate
```

## Build the portable customer-support reference package

The customer-support package is a separate post-candidate result. It does not redefine
the frozen engine's `RELEASE_READY` state. A successfully assembled and independently
verified bundle reports `PACKAGE_READY` under evidence schema `2.0.0-package`.

```bash
pmpe barebones package release \
  --contract examples/support-package/contract.json \
  --approval-receipt examples/support-package/approval-receipt.json \
  --expected-approver fixture-human \
  --evidence-root /tmp/customer-support-release-evidence \
  --run-id customer-support-release-run

pmpe barebones package build \
  --contract examples/support-package/contract.json \
  --approval-receipt examples/support-package/approval-receipt.json \
  --expected-approver fixture-human \
  --release-evidence-root /tmp/customer-support-release-evidence \
  --release-run-id customer-support-release-run \
  --expected-release-head-digest sha256:<trusted-terminal-event-digest> \
  --output /tmp/customer-support-package

pmpe barebones package verify \
  --bundle /tmp/customer-support-package \
  --expected-manifest-digest sha256:<trusted-build-output-digest>

python /tmp/customer-support-package/app.py --port 8080
```

The reference runtime uses only in-memory storage, a recorded response corpus, and a
fixture connector. Adopters provide their own compute, persistent storage, credentials,
live model and help-desk adapters, and production environment. The base package does not
claim live-model quality, prompt-injection resistance, vendor integration, reproducible
container digests, hosting, or production deployment. See the
[v1 architecture](docs/customer-support-package-v1.md).

`compile` reports `COMPILES` and the contract's recorded status; it does not imply
human approval or release eligibility. `status`, `evidence`, and `inspect` surface the
approval record from the verified ledger. `inspect` exits with code `3` for an
explicitly unverified direct-call run, even when its candidate is otherwise sealed.

`inspect` reads the candidate manifest from the verified evidence chain. When a
workspace is supplied, it fails with exit code `3` if any sealed file is changed or
missing, or if an untracked file or symbolic link appears. Use `--file <path>` to print
one digest-bound UTF-8 candidate file as escaped JSON before the human release decision.

The example provider returns scripted responses. It proves compiler-to-engine plumbing; it does not prove that an LLM can build the requested software.

For a real-model run, use the documented [Codex CLI provider](docs/real-model-provider.md) with saved ChatGPT subscription authentication. It does not require an API key. The optional Responses API example is not the promotion path. One live E1 run and its complete evidence bundle are now published; repeated-run and materially-different-contract reliability remain unproven.

A provider receives one JSON object on standard input:

```json
{"purpose": "code|advisory_review", "request": {}}
```

The contract must contain `contract_status: APPROVED` and `approved_by`; the CLI requires an exact `--expected-approver` match before invoking the provider. The provider must return one UTF-8 JSON object containing the same `request_digest`. Do not record provider credentials in contracts, commands, candidate workspaces, or evidence.

The Codex CLI path is deliberately explicit about its boundaries: it requires a host
`CODEX_HOME` authenticated with ChatGPT, gives the Codex child only an explicit safe
environment allowlist, and enforces ChatGPT
mode again on the command line. Its ephemeral read-only sandbox protects the provider
run; the separate Bubblewrap sandbox protects candidate execution. The prompt still
transits OpenAI. Subscription runs record pricing as not applicable per run rather than
claiming a zero-dollar API cost.

## Current evidence gap

PMOS publishes a compiler-shaped health contract plus an approval receipt bound to the exact contract digest; its pinned compatibility gate verifies the receipt, accepts the valid contract, rejects a post-approval edit, and rejects prose-only criteria. The published E1 run exercised that approved boundary with a real provider once. It does not prove live-model contract-authoring reliability, repeated behavior, or transfer to materially different contracts.

The completed E1 promotion gate recorded one real PMOS-authored contract reaching `RELEASE_READY` through a real provider with:

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
