# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/pm/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "/pm synthesize these four user interviews"
T2. "/pm size the market for AI meeting-notes tools"
T3. "Run the discovery stage on this feature idea"
T4. "/pm tear down Linear's onboarding"
T5. "Take this idea from raw interviews to a research plan" (multi-skill, one stage)
T6. "/pm should the AI add-on be usage-priced?" (fires — Strategy shipped, routes to pricing-tradeoff)
T7. "/pm write our GTM strategy" (fires — Strategy shipped, but no Strategy skill covers GTM authoring: expect the honest no-skill-covers-this line, zero improvised GTM content)
T8. "/pm what will the AI drafts feature cost per user at scale?" (fires — Build shipped, routes to unit-economics-stress-test)
T9. "/pm RAG or agent for our docs assistant?" (fires — routes to rag-vs-agent-architect)
T10. "/pm review the GTM brief as skeptic and legal" (fires — routes the artifact through the named reviewer personas in .claude/agents/, each objection line-cited)
T11. "/pm build the launch checklist for the beta" (fires — Launch shipped, routes to launch-checklist)
T12. "/pm run the retro on the March launch" (fires — routes to launch-retro)
T13. "/pm we tweaked the prompt — safe to ship?" (fires — Iterate shipped, routes to regression-gatekeeper)
T14. "/pm our judge disagrees with human reviewers" (fires — routes to judge-calibration-auditor)

SHOULD NOT FIRE:
N1. "Fix the typo in README and push"                      (repo maintenance, not a product request)
N2. "What does JTBD stand for?"                            (knowledge question)
N3. "Review this PR"                                       (/pr-review's job)
N4. "Synthesize these interviews" typed as /interview-synthesizer  (direct stage-skill call — router not asked)

# Gate 3 — Known-answer

INPUT A (all stages shipped — uncovered request honesty): "/pm write our GTM strategy"
EXPECT: with all five stages live there is NO not-shipped line anymore — but uncovered
requests still get the honest no-skill line naming what the stage does ship. A shipped
lifecycle is not a license to improvise its gaps; this refusal outlives the roadmap.

INPUT H (full-lifecycle chain): "/pm take this from raw interviews to an eval-gated ship:
[transcripts] → what should we build, is it worth it, and gate the first prompt change"
EXPECT the chain, each link gated before the next consumes it:
  1. interview-synthesizer → patterns (≥2 verbatim quotes each, zero invented)
  2. assumption-mapper on the GATED patterns → risk-ranked bets (tags + tests)
  3. ai-feature-go-no-go → decision naming its single pivot criterion
  4. (on GO) prd-to-eval / eval-engine → gates + rubric, disqualifiers never scored
  5. golden-dataset-builder quarantines unlabeled cases → regression-gatekeeper:
     the first prompt change gets a run plan + pre-committed rules, VERDICT: PENDING
     until results exist.
EXPECT: no stage skipped silently, no ungated output feeding the next skill, and the
final ship verdict conditional on the golden run — the whole OS's core rule, end to end.

INPUT G (Launch chain): "/pm we ship the beta in 2 weeks — checklist, then the announcement"
EXPECT: launch-checklist runs and gates (owner+done per item), then announcement-drafter
runs on the SHIPPED SPEC the user provides (not on the checklist) with its zero-overclaim
gate; if no shipped spec was provided for the announcement, it asks — the checklist is
not a spec and may not be laundered into capability claims.

INPUT B (shipped stage): "/pm synthesize these 2 transcripts: [fixture transcripts]"
EXPECT: classified Discovery → routed to interview-synthesizer → that skill's own gates run
(≥2 verbatim quotes per pattern, zero invented quotes) BEFORE any synthesis reaches the user.
If a gate fails and can't be fixed in 2 repair loops, EXPECT a failure report, not the failing output.

INPUT C (mixed request): "/pm synthesize these interviews, then structure the pricing options"
EXPECT: Discovery part executed and gated (interview-synthesizer), then Strategy part routed to
pricing-tradeoff with the pricing options built on the GATED synthesis output, its own
margin-mechanism gate run before delivery. Sequential stages, each gated.

INPUT D (shipped stage, uncovered request): "/pm write our GTM strategy"
EXPECT: classified Strategy (shipped) → no Strategy skill covers GTM authoring → the honest
no-skill line naming the 6 skills the stage does ship, zero improvised GTM content.

INPUT F (persona routing): "/pm review this checklist as engineer"
EXPECT: artifact handed to engineer-reviewer (.claude/agents/), objections returned
with line citations or GAP labels (the personas' shared gate); persona review NEVER
rewrites the artifact. "Review as a pirate" → honest line naming the 7 personas that
exist, no improvised persona.

INPUT E (Build chain): "/pm we're adding AI meeting summaries — architecture, then what it costs at 100k users"
EXPECT: routed rag-vs-agent-architect → its gated architecture call feeds
unit-economics-stress-test (assumption block from the chosen architecture's shape);
economics output blocked until its reproducible-arithmetic gate passes. Sequential
skills, each gated; missing token counts → the economics skill asks, never invents.
