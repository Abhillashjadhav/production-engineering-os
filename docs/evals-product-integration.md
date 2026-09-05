# Product evaluation connection

Owner request: complete the existing LinkedIn connection, preserve active drafting and
the native dashboard, provide reusable setup, and obtain independent model review.

## Approved boundaries

- No model/framework migration, product rubric edits, or drafting acceptance changes.
- A separate worker reads completed, explicitly selected exports. Network delivery is
  never part of the native generation process. Missing evidence stays missing.
- Preserve delivery outcome, raw failures, advisory mode, numeric scores, candidate
  identity, and repair cycle separately. Never equate a delivered draft with quality PASS.
- Comparable case identity is explicit input. Do not choose a frozen candidate versus
  recurring post slot for the owner. Never infer comparison identity from run ID.
- Baselines are explicitly selected and digest-bound; values are copied exactly.
- Explain what and where using recorded checks; explanations of why retain evidence
  confidence. The product does not gain automatic repair or approval authority.
- Detection evidence is independently labeled, separately reported per product and
  tool trajectory/system/output layer; >90% is strict. Empty evidence is unproven.
- Protected read access is available before any sharing. Viewer audience, maintenance
  cadence, the earlier 2% denominator, and the precise North Star formula stay owner decisions.

## Architecture implemented by this change

The running product saves its normal results. An independently started worker reads
completed results, makes a redacted copy, and delivers it to the shared dashboard.
Stopping the dashboard or worker does not stop LinkedIn drafting.

| Part | Responsibility | Boundary |
|---|---|---|
| LinkedIn and its native dashboard | Own research, generation, scores, delivery, and saved evidence | Existing models, scoring rules, acceptance, and dashboard remain product-owned |
| Local completed-run exporter | Preserve candidate identity, repair cycles, observed and recorded statuses, scores, advisory modes, delivery, and evidence digests | Explicit local export consent; no network, private prose, source bodies, URLs, or prompts |
| Separate Evals worker | Collect finished packages, bind explicitly chosen baselines, queue immutable results, and retry delivery | Separate process; no drafting or repair calls; changed snapshots fail validation |
| Shared Evals service | Authenticate writes/read access, store results, compare compatible checks, localize failures, and retain evidence | No inferred comparable input identity; no invented cause proof |
| Shared dashboard | Show delivery separately from quality; show native evidence, missing checks, comparison reasons, and each measurement layer | No averaging across the three layers; no claim that successful transport proves accuracy |
| Independent review records | Record actual silent failures, including misses, against stored cases and observations | Reviewer authority is separate from producer authority; test evidence stays separate from production evidence |

The worker uses a persistent outbox. Transient errors stay pending. Invalid or
permanently rejected items are quarantined without preventing valid later items
from delivery; existing quarantine remains visible on subsequent passes. Baseline
binding retains fully resolved immutable envelopes so successive comparisons use
the same bytes the receiver stores. Legacy stored digests remain compatible.

LinkedIn's native exporter remains local-only. The shared worker performs the
network delivery only with explicit `--allow-monitoring-export` and
`--allow-delivery`. It adds private export/context records without rewriting the
completed dashboards. No model migration, regeneration, publication, rubric
change, or golden-dataset update is part of this integration.

## Capabilities and limits

| Customer question | What this change supports | What still needs evidence or a decision |
|---|---|---|
| Did the draft arrive despite quality warnings? | Native delivery outcome and quality evidence are separate | Check one real saved run against its native dashboard |
| What failed, and where? | Recorded checks, candidate scores, stage/component locations, and missing evidence | The product must actually record checks for that layer |
| Did behavior worsen on the same input? | Explicit baseline, exact measurements, matching case/input and evaluation versions | Owner defines comparable cases and selects baselines |
| Why did it fail? | Recorded evidence and diagnosis confidence; graph-based localization remains distinct from causal proof | Confirming a cause requires suitable evidence; the exporter does not invent it |
| Do we catch silent failures? | Independent failure labels and separate tool/system/output recall | Enough representative reviewed failures, including misses, are required; >90% applies separately |
| Can others see the dashboard? | Separate viewer credential and local dashboard serving | Shared hosting, audience, and deployment configuration remain to be approved and tested |
| Can another product use it? | Installable shared service, connection check, folder watcher, queue, and retry commands | Product-specific checks and a mapping of saved results remain necessary |

Native LinkedIn packages that do not record a tool-trajectory check remain
NOT_EVALUATED for that check. Native candidate output scores do not stand in for
tool or system evidence. Source facts can preserve evidence without turning every
fact into a scored check. The source's advisory warning never becomes a new
product blocking gate merely because the dashboard records it.

The per-layer detection status is UNPROVEN with no reviewed silent failures,
BELOW_TARGET at or below 90%, and OBSERVED_ABOVE_TARGET above 90%. The latter is
an observed sample result, not a statistical assurance claim. Existing localization
audit measurements remain a distinct historical measure. The earlier 2% target's
denominator and the exact regression North Star formula are not settled here.

## Installation and verification

See [the quickstart](../products/pm-evals-web/QUICKSTART.md) for installation,
version context, explicit comparison identity, and local LinkedIn delivery.
The distribution script builds one wheel containing the API, commands, and
dashboard; recipients need Python 3.11/3.12 and no frontend build tools.

Installation time and product verification time are different. A three-minute
installation plus synthetic demo is a target with prerequisites available, not a
measured cold-install guarantee. Connecting an already instrumented product is
estimated in hours; defining missing product checks can take days. Real accuracy
validation depends on independently reviewed cases and operating cadence.

The integration verification exercises synthetic native results through the actual
exporter, HTTP delivery, storage, and dashboard API. Regression tests cover exact
baseline binding, preservation of evidence, role separation, retry/quarantine, and
independent per-layer detection accounting. This demonstrates connection behavior
within those fixtures; it does not establish accuracy on private live runs.
The final review/PR records report exact test results and any repository-wide
failures separately. Independent model review informs corrections and local-test
readiness; it does not replace product-owner decisions or live acceptance testing.

Before activating against existing work, install the reviewed changes in a separate
checkout, start a local dashboard, collect one completed real run, and compare its
saved native report with the shared view. Then enable the separate worker. No
merge into the running repository or public deployment is performed by the build.

## Remaining owner decisions

- Define comparable cases for each product and select baseline runs.
- Choose the audience and hosting before exposing a shareable dashboard.
- Set the human review and golden-dataset maintenance cadence; delivery polling
  every 30 seconds is merely a transport default.
- Resolve the earlier 2% denominator and the precise product-regression North Star
  formula before presenting those as accepted product metrics.

These are not silently filled in by implementation defaults. No automatic case
selection, dataset evolution, or product acceptance-policy changes are introduced.

## Independent review and reusable review prompt

The independent reviewer approved the corrected changes for local integration
testing. The review covered preservation of legacy digests, candidate evidence,
successive baseline binding, and persistent quarantine. API verification rejected
forged case identity with 422 and unauthorized roles with 401; concurrent
conflicting review submissions returned one 200 and one 409. This approval does
not establish missing native check coverage or production detection accuracy.

Give another model the two proposed repository revisions and this prompt:

> Independently inspect the shared Evals changes and the LinkedIn completed-run
> exporter. Verify claims against code and runnable tests; distinguish observed
> results from assumptions. Trace a completed native result through redaction,
> delivery, storage, comparison, and the dashboard. Check that delivery success,
> candidate scores, repair cycles, advisory failures, and missing evidence remain
> faithful to the native product. Exercise successive baseline comparisons,
> changed inputs/versions, offline retry, persistent quarantine, viewer/writer
> isolation, and independently labeled silent failures at each of the three
> layers. Assess whether stopping Evals can affect an active LinkedIn run.
> Identify any product decision the implementation made without authorization;
> case identity, sharing audience, review cadence, and unsettled metric formulas
> must remain explicit. Do not claim causal proof from graph localization or
> production accuracy from synthetic tests. Return blockers with file references,
> reproduction steps, and the smallest correction, followed by separate verdicts
> for local testing, unattended delivery, and wider product rollout. Estimate
> installation effort separately from adding meaningful checks to a new product.

## Verification record — 2026-09-05

- Shared backend: 253 tests passed, including both native cross-repository tests.
- Frontend: 106 tests passed; TypeScript and production build passed.
- Backend strict types and lint passed.
- Packaged wheel installed independently and served its bundled dashboard, assets,
  and synthetic overview. Startup was 0.89 seconds with dependencies already
  installed; this does not measure a cold network install.
- LinkedIn: 17 targeted tests passed after rebase on `da7cf63`, including the
  latest advisory research behavior; privacy check passed. Historical thresholds
  come from saved acceptance contracts, never the currently installed policy.
- The broader LinkedIn suite ran 762 tests with 11 failures and 10 errors in this
  workspace. Representative immutable SQLite and missing-fcntl failures reproduce
  on unchanged base; doctor also fails in this environment. This is not a claim
  that the entire native repository passes here.
- Final dependency audit was not completed: automatic approval review rejected
  transmitting dependency metadata to the public npm registry. The proposed
  development-only OpenAPI generator upgrade is included for normal CI audit.
- No private live run, public deployment, or existing generation process was used.

The LinkedIn proposal is [draft PR 157](https://github.com/Abhillashjadhav/Linkedin-research-posts/pull/157).
The shared CI connection check pins its native exporter revision rather than
following a moving branch. All experiments used synthetic data.
