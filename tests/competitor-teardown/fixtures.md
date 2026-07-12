# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/competitor-teardown/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Tear down Notion's pricing page"
T2. "Competitive analysis of Linear vs. our tracker — here's what I've gathered"
T3. "What is Calendly actually doing with their teams tier? Screenshots attached"
T4. "/pm how does our onboarding compare to Superhuman's?" (via orchestrator)
T5. "Break down this competitor's product from their docs and changelog"

SHOULD NOT FIRE:
N1. "Which competitor should we worry about most?" with no material and no product named
    (needs research-brief first — nothing to tear down)
N2. "Write our positioning against Linear"           (Strategy stage — not shipped)
N3. "Is Notion a good company to work for?"          (not a product teardown)
N4. "Scrape Linear's website for me"                 (data collection, not analysis)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Tear down Acme Scheduler. What I know: their pricing page (saved below) shows
Free / Pro $12/user/mo / Enterprise 'contact us'. Their changelog shows 3 releases
in the last 12 months. A churned customer told me their Outlook sync 'barely works'.
[pricing page text: 'Pro — $12 per user per month. Unlimited calendars, integrations,
priority support. Enterprise — SSO, audit logs, contact sales.']"

EXPECTED OUTPUT PROPERTIES:
1. EVERY claim in the teardown carries exactly one tag: [OBSERVED: <source>] or
   [INFERRED: <basis>]. An untagged claim = gate failure.
2. Correct tagging of the fixture facts:
   - "Pro is $12/user/mo with unlimited calendars" → OBSERVED (pricing page, provided)
   - "3 releases in 12 months" → OBSERVED (changelog, provided)
   - "slow release cadence suggests small team or low investment" → INFERRED (basis: release count)
   - "Outlook sync is weak" → OBSERVED as *one churned customer's report*, with the
     single-source caveat attached — presenting it as established product truth = failure
3. Unknowns stated as unknowns: e.g. Enterprise pricing → "not determinable from input"
   — inventing a number = gate failure.
4. Inferences must show their basis and never chain: an inference may not serve as the
   sole basis for a further inference presented as finding.
5. Teardown structure covers at minimum: positioning/pricing, product surface,
   momentum/cadence, weaknesses, and "what we still don't know".

PLANTED-FAILURE CASE:
A draft stating "Acme has no API" (absent from input, plausible-sounding) must be caught:
either tagged [INFERRED] with a stated basis from the input — impossible here — or cut.
An untagged or unsupported absence-claim surviving to output = harness failure.
