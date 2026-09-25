# Follow-up: review the implementation and the smallest task-store migration

Please proceed with the read-only repository review you offered: clone the
pinned sources, inspect the code, run the applicable offline checks, and return
your findings plus the smallest implementable migration proposal. Do not merge,
change production code, alter approved artifacts, invoke paid APIs or access
my laptop. This request authorizes review and disposable test outputs, not a
new live model generation or architecture migration.

**Starting status: implemented, not merged.** All six change PRs remain draft
and unmerged at our latest check. The 346-test combination is a proposed tree,
not main. No current-engine, owner-approved non-health end-to-end run has been
established by this evidence. Judge the proposed code and that missing outcome
separately. Do not treat passing tests as a completed product or owner approval.

## Corrections to our earlier response

1. **F-01: agree with the central gap.** Rejecting unsupported gates repairs
   silent omission, but does not complete the intended delivery path. There are
   **five gates, all five unbound**, not five of six. GATE-001 can bind the 14
   product ACs; the remaining four need process/evidence semantics. Determine
   whether a binding-only change is possible. Do not assume it is.
2. **F-03: mark current-run proof OPEN.** The old task-store run remains evidence
   of non-health capability on its pinned source. It is not evidence of current
   compatibility. Conversely, a compile-time gate block does not itself prove
   that the current runtime cannot express non-health behavior. Distinguish
   expressiveness, admission and demonstrated delivery.
3. **F-09: withdraw “source was not supplied.”** pm-evals-web is in PEOS, and
   your feedback says `observation-plane.tar.gz` was delivered. We did not inspect
   that archive in this repair. This chat's filename searches did not resolve it;
   that is an access limitation, not evidence you failed to provide it. If you
   retain the archive, inspect it alongside PEOS and record its hash/version.
   If unavailable, report that narrowly and request the exact missing source.
   Choosing which system survives remains the owner's HANDOVER decision (a).
4. **Agree on status framing:** lead with implemented-not-merged. Separately
   report review, merge and deployment. The latest technical CI passed on
   PEOS #208/#209, but draft review blocks/skips are not approval.
5. **Agree on scope:** career-assistant requirements are moved to a separate
   brief and are not criteria for this repair review.

## Source pins and existing evidence

The original full prompt and its six exact implementation pins are at:
https://github.com/Abhillashjadhav/production-engineering-os/blob/c4798341c0df41fc6e8cd014cacca3838cfec384/docs/evidence/integration-review-20260924/INDEPENDENT_REVIEW_PROMPT.md

This follow-up supersedes its F-03/F-09 dispositions and scope/status framing.
The revised full prompt and evidence are linked from:
https://github.com/Abhillashjadhav/production-engineering-os/pull/210

Core pins to inspect:

- Changed PEOS compiler/runtime, PR #209:
  `5ccc46ce220092451032397cd7a951a0e8d163e0`.
- Current PMOS handoff, PM-agent-OS PR #63:
  `0b6bd55152efc918f9a042fc898e961dcf527b96`.
- Historical approved PMOS task-store packet, PM-agent-OS PR #58:
  `33a35962d13fb13163d61beb938f9e593a742197`.
- Historical PEOS feature/runner, PR #203:
  `f7669c2cd1bb9600b0fe7bd26e621b95a3402fb1`.

Read `reviews/task-tracker-v1/contract.approved.json` in the historical PMOS
source. `strict-compatibility.json` in PEOS #210 records the five unbound gates.
Preserve that source contract and its approval, evaluator and freeze. Existing
task-store behavior and all 14 acceptance expectations remain unchanged.

## Proposed engineering change — evaluate before implementation

**Question to resolve first:** what is the smallest semantics-preserving change
that produces a valid task-store run on the changed engine with every declared
gate checked and tied to the exact run/candidate?

Our hypothesis is to retain AC conjunctions for product behavior and reuse the
existing task-store verification/evidence collectors for process gates, adding
only the missing typed bindings and enforcement. This is a hypothesis, not a
chosen new framework. First check whether the existing system already has the
necessary path. Recommend reuse, an adapter or a narrow extension with exact
files and tests; explain any unavoidable contract change.

| Gate | Existing meaning to preserve | Candidate implementation to assess |
|---|---|---|
| GATE-001 | All AC-001–AC-014 pass unchanged | Explicitly bind all 14 AC IDs using the existing conjunction mechanism. |
| GATE-002 | Meaningful baseline assertion failure; persistence/filtering defects fail for the intended reason | Bind actual baseline and negative-control evidence to exact evaluator, mutation and run identities; reject unrelated crashes or missing prerequisites. |
| GATE-003 | Every approval-bound digest matches immediately before and after each authoritative check | Reuse the existing digest checks; enforce completeness, timing/order and identity, not only “zero mismatches” over a possibly empty list. |
| GATE-004 | Actual in-session model request/response, commands, generated artifact and criterion observations retained; no undisclosed repair | Validate provenance and artifact/run links. Determine whether a fresh generation is required. Historical evidence cannot be relabeled as a new generation; file existence alone does not establish truth. |
| GATE-005 | Truthfully disclose root/receipt/isolation/reproduction limits | Bind the report to the actual execution profile and require the relevant disclosures. State which aspects can be checked mechanically and which remain attestations under the approved trust model. |

A correct refusal and an engineering gap can both exist: the compiler may be
right to block while the system still lacks the implementation needed to admit
the real contract. Explicitly distinguish them. Renewed approval is necessary
for changed bound meaning/source, but is not sufficient to supply missing checks.

Do not bind GATE-002–005 to unrelated passing ACs, delete them, turn “evidence
present” into “evidence valid,” add hard-coded PASS results, issue owner approval,
or modify the frozen evaluator to get a green run. Do not weaken the gates merely
to stay within the existing binding format. Preserve historical terminal claims.

Propose a draft migration patch/plan with changed paths, proposed contract diff,
new source/freeze identities to be approved, execution sequence and rollback.
Do not mark the draft approved. Identify the exact owner decision only after
the reviewable technical proposal exists. Separate retained-artifact replay from
fresh generation, and spell out what each can establish.

Minimum verification proposal: valid current-run evidence can pass; missing,
wrong-run, stale, tampered or incomplete evidence blocks; both seeded defects
fail for the intended reason; all 14 product criteria retain their meaning;
every gate result refers to the exact contract/run/candidate; no release event
appears when a required gate is FAIL or NOT_EVALUATED. Do not claim root-resistant
authentication or tamper prevention from hashes alone.

## F-09: prepare the decision; do not make it

Inspect both implementations if accessible. Compare actual capabilities, caller
dependencies, stored data, UI/worker reuse, evidence contracts, known measurement
defects, migration effort and rollback. Separate defects you reproduce from
claims in HANDOVER. Present the adapter/consolidation and replacement options,
with evidence and reversal triggers, for owner decision (a). Do not delete either
system, declare one the winner, or initiate a new dashboard build in this review.

## Return this

Start with at most three bullets: implementation verdict, the smallest proposed
fix and any real owner decision. Then give:

1. Exact commits/files inspected and commands actually run, with outcomes and
   access limits. Verify the draft/unmerged status rather than assuming it.
2. A gate-by-gate table: existing check, missing behavior, smallest proposed
   change, regression test, approval consequence and remaining trust limit.
3. Whether you accept or reject our narrow-extension hypothesis, with reasons.
   Identify exact code changes where possible; do not invent checked code.
4. Separate verdicts for the historical demonstration, the current proposed
   engine, the migration proposal and merge readiness. An unexecuted migration
   remains a proposal, even if the reasoning looks sound.
5. A short F-09 decision brief if both sources were inspected; otherwise state
   exactly what source is missing from your environment.

No generic rewrite, unrelated product interview or additional model-agreement
round is needed. If the smallest repair is larger than a binding change, say so
and explain which original gate semantics force that work.
