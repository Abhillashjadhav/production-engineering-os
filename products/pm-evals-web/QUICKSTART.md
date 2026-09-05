# Evals: open a dashboard, then connect a product

The dashboard helps you see which checks failed, where they failed, and the
recorded evidence. LinkedIn keeps making posts and its existing dashboard keeps
working. A separate process sends evaluation results after a run has finished.

**A three-minute installation and sample dashboard is the target, not a measured
cold-install promise.** Connecting real product evidence takes additional work.

| What you want | Planning estimate | What completion means |
|---|---|---|
| Install and open the sample | Target: about 3 minutes with Python and a built wheel available | Synthetic dashboard opens; no product is connected |
| Connect a product that already records useful checks | Hours, depending on its saved results and access setup | A completed run reaches the dashboard with matching results |
| Connect a product that has no suitable checks | Days, depending on the product | Product-specific checks and example failures must be defined and tested |
| Establish real failure-detection accuracy | Depends on reviewed cases and run cadence | Each layer has its own independently reviewed evidence |

## 1. Open the sample

Requires Python 3.11 or 3.12. Install the wheel supplied with this change; it
includes the dashboard, so the receiving machine does not need Node.

```bash
python3 -m venv .evals-venv
source .evals-venv/bin/activate
python -m pip install /absolute/path/to/pm_evals_web_backend-0.2.0-py3-none-any.whl
pm-evals serve --demo
```

Open <http://127.0.0.1:8000>. Everything in demo mode is synthetic. Stop the
server with Ctrl+C before starting the real-data server on the same port.
Use the actual wheel filename if its version differs.

To build the wheel from a checkout, maintainers also need Node 22.18+ and npm:

```bash
python -m pip install 'setuptools>=68' wheel
python products/pm-evals-web/backend/scripts/build_distribution.py
```

The output is under `products/pm-evals-web/backend/dist/`. The script installs
frontend dependencies from the lockfile, builds the dashboard, and packages it
with the Python application. `--skip-install` reuses dependencies already
installed with `npm ci`. The build does not add generated dashboard assets to git.

## 2. Start a local dashboard for real results

Choose three different credentials using your normal secret-management process.
The producer sends results, the viewer reads them, and the reviewer records
independent failure labels. Set these in the server terminal; do not put secret
values in a committed file:

```bash
export PM_EVALS_INGEST_TOKEN='<producer-secret>'
export PM_EVALS_VIEWER_TOKEN='<different-viewer-secret>'
export PM_EVALS_ADJUDICATION_TOKEN='<different-reviewer-secret>'
pm-evals serve --data-dir /absolute/path/to/private-evals-data
```

Open <http://127.0.0.1:8000> and enter the viewer credential when requested.
This command listens on this machine only. A public/shareable deployment still
needs an approved audience, hosting, HTTPS, and production access configuration.
The local command above is not the production multi-product deployment setup.

## 3. Connect completed LinkedIn runs

Use a LinkedIn checkout containing the completed-dashboard export changes and
the matching `adapters/linkedin-os.settings.json` from this Evals change. The
worker reads completed `eval-dashboard.html`, `run-dashboard.json`, and
`eval-dashboard.json` files beneath that checkout's `data/private` directory.
It does not start research, drafting, repair, or a model call.

First create a private JSON context file outside git. Replace every version
placeholder below with the public-safe identifier of the **actual saved run's**
configuration. These labels describe what already ran; they do not change models
or acceptance rules. Use one worker/context for runs with that configuration.

```json
{
  "comparison_run_id": "NO_BASELINE",
  "product_version": "replace-with-product-version",
  "use_case_version": "replace-with-use-case-version",
  "deployment_id": "replace-with-deployment-id",
  "model_provider": "replace-with-provider",
  "model_name": "replace-with-model-name",
  "model_snapshot": "replace-with-model-snapshot",
  "prompt_version": "replace-with-prompt-version",
  "config_version": "replace-with-config-version",
  "toolset_version": "replace-with-toolset-version",
  "evaluator_version": "replace-with-evaluator-version",
  "rubric_version": "replace-with-rubric-version",
  "golden_dataset_version": "replace-with-dataset-version",
  "production_cohort": "replace-with-cohort"
}
```

The worker fills run ID and timestamps from each completed run. Do not put a
shared case ID or input fingerprint in this context: unrelated inputs must not
silently become comparable.

In a separate terminal, activate the Evals environment and supply the producer
credential. Run one collection/delivery pass first:

```bash
export PM_EVALS_INGEST_TOKEN='<same-producer-secret-as-server>'
pm-evals linkedin \
  --repo /absolute/path/to/Linkedin-research-posts \
  --context /absolute/path/to/private-monitoring-context.json \
  --settings /absolute/path/to/production-engineering-os/products/pm-evals-web/adapters/linkedin-os.settings.json \
  --outbox /absolute/path/to/private-evals-outbox \
  --url http://127.0.0.1:8000 \
  --allow-monitoring-export \
  --allow-delivery \
  --once
```

Confirm `invalid`, `pending`, and `quarantined` are all zero. A queued count
includes exports seen again; duplicate delivery does not create duplicate runs.
Compare the dashboard's candidate scores, warnings, and delivery outcome with
the saved native dashboard. Missing checks remain **NOT_EVALUATED**.

Remove `--once` to keep collecting automatically while this separate process
runs. `--interval 30` controls delivery polling in seconds; it is not the cadence
for investigating failures or changing the golden dataset. To stop collection,
stop this process. LinkedIn generation continues independently.

Connection failures retain pending results for retry. Permanently rejected
results remain quarantined and visible until an operator resolves them. A
successful later delivery does not erase earlier quarantine warnings. Do not
delete queue files simply to make the status green.

### Compare the same input across runs

Comparison is optional. Without an explicitly comparable baseline, results
still appear, but regression comparison may be unavailable.

Before first collection, the product owner must decide what counts as the same
case: for example, a frozen draft re-evaluated versus a recurring post slot.
For each comparable completed run, write an owner-only
`monitoring-identity.json` in that run's folder with:

- `case_id`: an opaque identifier following that agreed case definition;
- `input_fingerprint`: `sha256:` followed by the 64 hex digits of the agreed input;
- `comparison_run_id`: the exact earlier native run ID to compare, or `NO_BASELINE`.

Do not copy a fingerprint between different inputs just to enable comparison.
The worker binds explicitly selected baselines and their exact values, including
chains of successive runs. An existing externally stored baseline may require
its verified `comparison_sha256`. Changed inputs or evaluation versions can
make comparison unavailable; the dashboard explains that distinction.

Completed exports and binding records are immutable. Set version context and
identity before collection. If a saved run or configuration changes afterward,
the worker stops accepting that changed record; use a new run identity after
reviewing the change.

## 4. Connect another product

Every product can use the same dashboard and delivery commands. Each product
still needs to supply its own meaningful checks and evidence. The template does
not automatically learn what correct behavior means for a new product.

```bash
pm-evals check \
  --run /absolute/path/to/completed-run.normalized.json \
  --settings /absolute/path/to/product.settings.json
pm-evals watch \
  --directory /absolute/path/to/completed-exports \
  --settings /absolute/path/to/product.settings.json \
  --outbox /absolute/path/to/private-product-outbox \
  --url http://127.0.0.1:8000 \
  --allow-delivery \
  --once
```

`check` validates that the supplied record can be read and lists missing checks.
It does not certify product quality. For an explicitly chosen canonical baseline,
use `check` or `submit` with `--baseline`; the generic folder watcher does not
choose baselines for you. The settings examples are in `products/pm-evals-web/adapters/`; they define which saved product checks the dashboard expects.

Tool behavior, system behavior, and output quality are reported individually.
Silent-failure recall requires independently labeled failures, including missed
ones, and must exceed 90% in **each** layer. An empty layer is unproven; a working
connection or synthetic demo does not establish that accuracy.
