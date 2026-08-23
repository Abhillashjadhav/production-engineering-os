# Reference real-model provider

Issue: #143

`examples/barebones/openai-responses-provider.py` is the first documented real-model
adapter for the frozen `ModelProvider` boundary. It uses the OpenAI Responses API,
strict Structured Outputs, and `store: false`.

Official references:

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Responses API migration and storage](https://developers.openai.com/api/docs/guides/migrate-to-responses)

The script uses only the Python standard library. It is an adapter example, not a
mandatory OpenAI dependency in `pmpe`.

## Environment

```bash
export OPENAI_API_KEY='<set outside the repository>'
export PMPE_OPENAI_MODEL='<an available structured-output-capable model>'
export PMPE_OPENAI_INPUT_USD_PER_MILLION='<current input-token price>'
export PMPE_OPENAI_OUTPUT_USD_PER_MILLION='<current output-token price>'
```

The reference adapter sends credentials only to
`https://api.openai.com/v1/responses`; the endpoint is intentionally not configurable.
Do not put credentials in a contract, provider command, candidate workspace, shell
history, evidence directory, or committed file.

## Run

```bash
pmpe barebones examples/barebones/e1-contract.json \
  --workspace /tmp/pmpe-real-e1-candidate \
  --run-id real-e1 \
  --repository-root /tmp/pmpe-real-e1-evidence \
  --approval-receipt examples/barebones/e1-approval-receipt.json \
  --expected-approver fixture-human \
  --provider-command "python examples/barebones/openai-responses-provider.py"
```

The provider records non-secret metadata returned through the protocol: provider,
resolved model name, prompt version, response id, usage, and estimated cost when both
current per-million-token prices are configured. Prices are never hard-coded because
they change; the operator must supply the rates used for the evidence bundle. The core
still owns the request digest, output limits, candidate-path validation, deterministic verification,
and evidence chain. Successful provider calls with complete non-secret provider metadata
also emit normalized `provider_behavior` observations (request, output, provider, model,
and prompt-version digests) into the hash-chained events. Those observations enable
cross-run drift comparison; repeated real-provider drift remains unproven until P1 runs
publish comparable observations.

## Evidence rule

The presence of this script does not prove a real-model run. Promotion requires a
recorded run whose contract, plan, provider metadata, attempts, token usage, elapsed
time, terminal state, candidate manifest, and evidence chain are published together.

The current example contract is structurally valid but remains a deliberately tiny
health-action fixture. A successful run is E1 evidence, not breadth or platform
evidence.
