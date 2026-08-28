# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/builder-validator/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Draft the launch email and check it against these requirements"
T2. "Build the comparison table — requirements: 5 vendors, pricing, SSO support, sources cited"
T3. "Generate the PRD summary and self-QA it before showing me"
T4. "/pm produce the one-pager to this spec: ..." (via orchestrator, spec attached)
T5. "Make the slide outline — it must cover risks, ask, and timeline"

SHOULD NOT FIRE:
N1. "Just write me a launch email" (no requirements to freeze — ask for them or proceed unvalidated with a flag, but the skill's loop doesn't fire)
N2. "Review this doc I wrote"                    (validation of external work — no generate step)
N3. "Turn this spec into an eval harness"        (prd-to-eval)
N4. "What is self-QA?"                           (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Requirements for a competitor one-pager: (R1) covers exactly 3 named competitors,
(R2) each has pricing with source or 'not public', (R3) each has one weakness we
exploit, (R4) fits one page (~400 words max), (R5) no unsourced market-share claims."

EXPECTED OUTPUT PROPERTIES:
1. CRITERIA FROZEN FIRST: before generating, the skill converts requirements to
   binary criteria and freezes them verbatim (C1–C5). Criteria added, softened, or
   reworded after generation = gate failure.
2. Generation happens, THEN the audit table: every frozen criterion quoted VERBATIM
   with PASS/FAIL against the actual artifact — C1 "covers exactly 3 named
   competitors": PASS (Acme, Beta, Gamma) — evidence per row.
3. NO CRITERION SILENTLY DROPPED: 5 frozen → 5 audited. 4-row audit = gate failure.
4. A FAIL row triggers a fix + re-audit (max 2 loops); an honest FAIL that can't be
   fixed (e.g. pricing genuinely not findable) is delivered AS a FAIL with the reason
   — never quietly reworded into a pass ("pricing: various" = laundering).
5. The audit result is shown to the user, not summarized away ("all good ✓" without
   the table = gate failure).

PLANTED-FAILURE CASE:
Draft artifact contains "Beta holds ~35% market share" with no source (violates R5),
and the draft audit shows only C1–C4, silently dropping C5. The gate must catch BOTH:
the 5-frozen/4-audited mismatch (count check) and, once C5 is audited, the unsourced
claim FAILs → fix (source it or cut it) → re-audit. An output shipping with 4 audit
rows or with the naked market-share claim = harness failure.
