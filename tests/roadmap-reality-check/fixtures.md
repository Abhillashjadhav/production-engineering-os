# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/roadmap-reality-check/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Reality-check this roadmap against our unit economics"
T2. "Which of these Q3 roadmap items actually pay for themselves?"
T3. "Audit this roadmap — what's economically justified?"
T4. "/pm here's the 2027 roadmap and our margins — what survives contact with the P&L?" (via orchestrator)
T5. "Does this AI-feature lineup make economic sense at our price point?"

SHOULD NOT FIRE:
N1. "Prioritize this roadmap by customer impact"    (prioritization without economics — different ask)
N2. "Build the roadmap for next year"               (authoring — needs a roadmap to audit)
N3. "Size the market for feature X"                 (opportunity-sizer)
N4. "What is unit economics?"                       (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Roadmap (B2B SaaS, $49/user/mo, gross margin 78%, ~2,000 paying users, CAC $900,
churn 2.2%/mo):
R1. AI meeting summaries on every call (est. LLM cost ~$6/user/mo at current usage)
R2. SSO + audit logs (unblocks 3 stalled enterprise deals, ~$110k ARR combined, per sales notes)
R3. Free tier to drive PLG growth
R4. Rebuild the settings UI (support tickets cite it in 9% of contacts)
R5. Usage-based billing migration"

EXPECTED OUTPUT PROPERTIES:
1. EVERY item tagged `SUPPORTED` or `UNSUPPORTED`, each with a stated economic
   mechanism — the causal chain to revenue, margin, retention, or CAC, quantified
   from the provided numbers where possible. A tag without a mechanism = gate failure.
2. Expected reasoning the audit must surface:
   - R1: $6/user/mo COGS against $49 price cuts gross margin from 78% to ~66% —
     mechanism must show the margin math and tag depends on a stated retention/pricing offset;
     with none provided in input → UNSUPPORTED (as stated).
   - R2: $110k ARR against stated CAC/margin → SUPPORTED via named enterprise deals
     (source: sales notes, per input) — mechanism: direct ARR unblock.
   - R3: free tier has NO stated conversion assumption or serving cost in input →
     UNSUPPORTED (as stated) — mechanism missing, and the audit must name what number
     would flip it (conversion rate × serving cost bound).
   - R4: mechanism must route through support cost or churn (9% of contacts), and
     flag that ticket→churn linkage is assumed, not provided.
3. All arithmetic uses ONLY input numbers; any other figure is labeled [ESTIMATE] with
   derivation (no invented benchmarks like "PLG converts at 3%").
4. UNSUPPORTED ≠ kill: each unsupported item states the missing evidence that would
   flip it to supported.
5. Summary line: N supported / M unsupported, and the roadmap's single biggest
   economic exposure named.

PLANTED-FAILURE CASE:
A draft tagging R3 SUPPORTED "because PLG typically converts 2-5% and expands the
funnel" — an imported industry benchmark with no basis in the input — MUST be caught:
either relabeled [ESTIMATE] with stated derivation and the tag downgraded to
UNSUPPORTED (as stated), or cut.
