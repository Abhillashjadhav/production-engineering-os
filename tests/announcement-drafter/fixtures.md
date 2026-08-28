# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/announcement-drafter/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Draft the launch announcement for AI summaries"
T2. "Write the internal and external announcement for the March release"
T3. "Changelog + customer email for the new feature — shipped spec below"
T4. "/pm announce the launch" (via orchestrator, spec attached)
T5. "Blog-post draft for the feature we just shipped"

SHOULD NOT FIRE:
N1. "Write the stakeholder status update"         (stakeholder-update — internal status, not announcement)
N2. "Draft the GTM one-pager"                     (gtm-brief)
N3. "Should we announce this now or wait?"        (timing decision, not drafting)
N4. "Rewrite our homepage"                         (marketing site, not a launch announcement)

# Gate 3 — Known-answer

FIXTURE INPUT (shipped spec):
"Shipped: AI meeting summaries. What it does: generates a text summary after each
calendar meeting that has a linked video call; supports English only; summary
includes action items when speakers state them explicitly; admin can disable
workspace-wide; EU data residency respected; +$10/seat add-on. NOT in this release:
real-time summaries, integrations beyond our own video, multi-language, custom
templates, mobile app surface."

EXPECTED OUTPUT PROPERTIES:
1. THE OVERCLAIM GATE: zero capability claims not present in the shipped spec. Every
   capability sentence in both drafts must map to a spec line. The NOT-in-release
   list is a blocklist: any claim touching it (real-time, other-vendor calls,
   languages, mobile) = gate failure.
2. Precision survives marketing: "captures action items when speakers state them
   explicitly" may be tightened stylistically but never rounded up to "automatically
   tracks all your action items". Softening qualifiers off a claim = overclaim.
3. TWO DRAFTS, one truth: internal (team: what shipped, what's explicitly not in
   this release, known limits — the NOT list appears verbatim) and external
   (customers: value framing, English-only and admin-control stated, price stated).
   The external draft may omit roadmap negatives but may never contradict them.
4. No invented reception, stats, or social proof ("customers are already raving").
   Pre-launch announcement = zero usage claims.
5. Claim-to-spec map included: each capability sentence indexed to the spec line it
   derives from — the audit trail for the gate.

PLANTED-FAILURE CASE:
An external draft containing "works with all your video-call tools and meetings in
any language" — two blocklist hits (integrations beyond own video; multi-language)
dressed as one friendly sentence — MUST be caught by the overclaim gate via the
claim-to-spec map (no spec line supports it) and rewritten to the spec's actual
scope ("meetings on [our] video calls, English today").
