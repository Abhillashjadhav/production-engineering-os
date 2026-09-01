# Horizontal monitoring adapters

Every product uses the same mapper. A product integration contains only:

1. a versioned settings JSON file defining case types, checks, stages,
   dependencies, owners, thresholds, safe summaries, and remediation; and
2. a narrow exporter from the product's native eval evidence to
   `normalized-eval-run/0.1`.

The exporter must not implement thresholds, dependency diagnosis, transport,
retry policy, dashboard rendering, or causal claims. It must emit allowlisted
facts and hashes, never raw inputs or outputs.

```bash
PYTHONPATH=backend/src python backend/scripts/map_monitoring_run.py \
  --settings adapters/dream-job.settings.json \
  --run data/private/dream-job.normalized.json \
  --output data/private/dream-job.run-envelope.json
```

Persist lifecycle evidence before evaluation, enqueue the completed normalized
run afterward, then flush the durable outbox:

```bash
PYTHONPATH=backend/src python backend/scripts/monitoring_outbox.py \
  --outbox-dir data/private/monitoring-outbox enqueue-receipt --receipt receipt.json

PYTHONPATH=backend/src python backend/scripts/monitoring_outbox.py \
  --outbox-dir data/private/monitoring-outbox enqueue-run \
  --settings adapters/dream-job.settings.json --run dream-job.normalized.json

PM_EVALS_DREAM_JOB_TOKEN=... PYTHONPATH=backend/src \
python backend/scripts/monitoring_outbox.py \
  --outbox-dir data/private/monitoring-outbox flush \
  --base-url https://monitoring.example --token-env PM_EVALS_DREAM_JOB_TOKEN
```

The committed Dream Job and LinkedIn settings prove the first two integrations.
The conformance test maps a third product by changing settings only.
