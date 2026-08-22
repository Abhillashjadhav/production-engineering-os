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
```

`PMPE_OPENAI_BASE_URL` is optional and defaults to `https://api.openai.com/v1`.
Do not put credentials in a contract, provider command, candidate workspace, shell
history, evidence directory, or committed file.

## Run

```bash
pmpe barebones examples/barebones/e1-contract.json \
  --workspace /tmp/pmpe-real-e1-candidate \
  --run-id real-e1 \
  --repository-root /tmp/pmpe-real-e1-evidence \
  --provider-command "python examples/barebones/openai-responses-provider.py"
```

The provider records non-secret metadata returned through the protocol: provider,
resolved model name, prompt version, response id, and usage. The core still owns the
request digest, output limits, candidate-path validation, deterministic verification,
and evidence chain.

## Evidence rule

The presence of this script does not prove a real-model run. Promotion requires a
recorded run whose contract, plan, provider metadata, attempts, token usage, elapsed
time, terminal state, candidate manifest, and evidence chain are published together.

The current example contract is structurally valid but remains a deliberately tiny
health-action fixture. A successful run is E1 evidence, not breadth or platform
evidence.
