# Reference real-model providers

Issues: #143, #160

The frozen `ModelProvider` boundary supports two standard-library reference adapters:

- `examples/barebones/openai-responses-provider.py` uses the OpenAI Responses API,
  strict Structured Outputs, and `store: false`.
- `examples/barebones/codex-cli-provider.py` uses a locally installed Codex CLI with
  saved **ChatGPT subscription** authentication. It does not accept API-key auth.

Neither adapter is a mandatory dependency of `pmpe`. Their presence and mocked tests
prove adapter plumbing only; they do not prove a real-model run.

Official references:

- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses API migration and storage](https://developers.openai.com/api/docs/guides/migrate-to-responses)

## ChatGPT subscription adapter

### Preconditions

Install the Codex CLI, run `codex login`, choose **Sign in with ChatGPT**, and complete
the browser flow. Confirm the active method before running PEOS:

```bash
codex login status
```

The adapter depends on saved host authentication in `CODEX_HOME` (by default
`~/.codex/auth.json` or the operating-system keyring). That credential state is not
copied into the repository, candidate workspace, prompt, provider response, or evidence.
The adapter gives the network-connected Codex child only an explicit environment
allowlist (`PATH`, auth/config locations, locale, terminal, temporary-directory, and TLS
certificate locations). API keys, cloud credentials, repository tokens, database URLs,
and unrelated host variables are not forwarded. It checks `codex login status` and
passes the explicit override `forced_login_method="chatgpt"`. It fails closed unless
both controls select ChatGPT.

### Run

```bash
pmpe barebones run examples/barebones/e1-contract.json \
  --workspace /tmp/pmpe-codex-e1-candidate \
  --run-id codex-e1 \
  --repository-root /tmp/pmpe-codex-e1-evidence \
  --approval-receipt examples/barebones/e1-approval-receipt.json \
  --expected-approver fixture-human \
  --provider-command "python examples/barebones/codex-cli-provider.py" \
  --provider-timeout 960
```

The adapter fixes the run to `gpt-5.6-sol` with `xhigh` reasoning and invokes
`codex exec` with an ephemeral session, JSONL telemetry, a read-only Codex sandbox,
ignored user configuration and rules, disabled web search, and a purpose-specific
output schema. It runs in a fresh temporary working directory and supplies the complete
request through stdin so contract content does not appear in the process argument list.
Codex stdout and stderr are captured; only one digest-bound PEOS JSON response is
written to adapter stdout.

The Codex execution budget defaults to 900 seconds and can be lowered with
`PMPE_CODEX_TIMEOUT_SECONDS`. The outer `--provider-timeout` defaults to 960 seconds;
PMPE passes that value to the adapter, which clamps its execution budget to remain
strictly below the outer deadline. Codex inherits the adapter's process group, so an
outer timeout terminates both instead of leaving an authenticated orphan process. The
adapter deducts actual authentication and version-preflight time before assigning the
Codex execution budget. After the provider leader exits, PMPE observes that exit without
reaping its PID, fences the complete provider process group, and only then reaps the
leader; this also removes descendants after an inner timeout or output-limit failure.
Stdout and stderr are bounded while Codex is running rather than after completion. Excess
telemetry bytes are drained and discarded so a valid authoritative result is not rejected
solely because a progress stream is verbose. The independent result-file limit remains a
hard failure.

These controls have precise limits:

- `--ephemeral` prevents Codex session-rollout persistence; it is not a privacy control.
  The approved contract, compiled plan, candidate file map, and findings still transit
  OpenAI as the model prompt.
- Codex's read-only sandbox constrains the provider process. It is separate from the
  PEOS Bubblewrap sandbox that later executes candidate code. A temporary working
  directory does not imply that Codex has no read access elsewhere on the host.
- One PEOS model call contains one `codex exec` agent loop. Codex may take multiple
  internal turns that PEOS cannot individually count or govern. PEOS still bounds the
  outer calls, output bytes, attempts, wall time, digest binding, candidate paths,
  deterministic verification, and evidence chain.
- Subscription usage is recorded with
  `pricing.source = "chatgpt_subscription"` and
  `per_run_cost_applicable = false`. A core `estimated_cost_usd` counter of `0.0`
  therefore means no per-run API price applies, not that the subscription is free.

The adapter records the Codex CLI version without imposing a version allowlist.
`prompt_version` contains only the adapter version and reasoning effort; the optional
CLI-version probe is separate telemetry, so a transient failed probe cannot be
misreported as a prompt-configuration change. Behavior comparison records CLI-version
changes as a separate attribution field only when both runs recorded known versions;
`unknown` telemetry is never treated as causal attribution.

The `model` field records the configured Codex model name; ChatGPT subscription auth does
not make that name an immutable provider-version pin. The #146 matrix therefore requires
attribution only for its planted `prompt_version` change and must not claim model-version
causality when the provider does not expose one.

Issue #146 also defines one planted, allowlisted prompt profile named `drift-eval-v2`.
It exists only to prove that a real behavior change can be detected alongside a recorded
prompt-version change. Unknown profile names fail before authentication or model execution.
The default profile and its historical `prompt_version` remain unchanged.

Run the complete repeated-provider matrix with:

```bash
python examples/barebones/run_real_behavior_drift_eval.py
```

The runner explicitly removes `OPENAI_API_KEY` and `CODEX_API_KEY`, rechecks ChatGPT login,
requires a clean source checkout, and packages failures as evidence. Immediately before
sealing the archive it re-verifies the Git head/worktree, provider digest, Codex CLI
version, and Python version captured at the start. Any mid-matrix identity change fails
the gate. A custom `--output-dir` must be outside the checkout so generated evidence
cannot masquerade as source drift. The outer run wrapper covers the complete configured
model-call budget plus bounded verification overhead, leaving each inner provider timeout
responsible for fencing its complete Codex process group before the wrapper can advance
the matrix. The planted experiment also passes only when `prompt_version` is the sole
provider-configuration attribution; a simultaneous CLI, model, or provider change is a
confounded experiment and fails closed. The runner does not silently fall back to the
Responses API.

## Responses API adapter

Configure credentials and a structured-output-capable model outside the repository:

```bash
export OPENAI_API_KEY='<set outside the repository>'
export PMPE_OPENAI_MODEL='<available model>'
export PMPE_OPENAI_INPUT_USD_PER_MILLION='<current input-token price>'
export PMPE_OPENAI_OUTPUT_USD_PER_MILLION='<current output-token price>'
```

The endpoint is fixed to `https://api.openai.com/v1/responses` so a redirect cannot
forward the bearer token. Run it with the same command above, replacing the provider:

```bash
--provider-command "python examples/barebones/openai-responses-provider.py"
```

Prices are not hard-coded; the operator supplies the rates recorded in the evidence
bundle. Do not put credentials in a contract, provider command, candidate workspace,
shell history, evidence directory, or committed file.

## Usage mapping

PEOS consumes `usage.input_tokens`, `usage.output_tokens`, and an optional
`usage.estimated_cost_usd`. Both adapters keep `output_tokens` output-only. The Responses
adapter preserves the provider's complete usage object, including any nested cached or
reasoning details. The Codex adapter records `cached_input_tokens` and
`reasoning_output_tokens` as additional keys. Missing Codex JSONL telemetry does not
invalidate a schema-valid result and records `telemetry_status = "unavailable"`.
Oversized stdout or stderr is retained only up to the configured cap and records
`telemetry_status = "truncated"`; any complete usage event captured before truncation is
preserved, otherwise input and output fall back to zero.

Successful responses with complete non-secret provider metadata also emit normalized
`provider_behavior` observations into hash-chained events. Those observations enable
cross-run drift comparison; repeated real-provider drift remains unproven until
comparable real runs are published.

## Evidence rule

Promotion requires a recorded run whose contract, plan, provider metadata, attempts,
token usage, elapsed time, terminal state, candidate manifest, and evidence chain are
published together. The current example contract is a deliberately tiny health-action
fixture. A successful run is E1 evidence, not product breadth, reuse, or platform
evidence.
