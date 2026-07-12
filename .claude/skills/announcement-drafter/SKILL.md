---
name: announcement-drafter
description: "Launch-stage skill: turns a shipped spec into an internal/external announcement pair with zero capability claims beyond what actually shipped — every claim mapped to its spec line. Use when a launch needs its announcements — 'draft the launch announcement', 'internal and external announcement for the release', 'changelog + customer email', 'blog post for the feature we shipped' — or when /pm routes such a request here. Do NOT use for internal status updates (stakeholder-update), GTM one-pagers (gtm-brief), announce-now-or-wait timing decisions, or general marketing-site copy."
argument-hint: "<the shipped spec — including what is explicitly NOT in this release — + audiences and channel>"
---

# Announcement Drafter

Marketing energy, spec-bounded truth. Every capability sentence traces to a spec line — the announcement can shine, it cannot stretch.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Zero overclaims:** every capability claim in both drafts maps to a line in the shipped spec. The spec's NOT-in-this-release list is a blocklist — a claim touching it fails, however friendly the phrasing. The claim-to-spec map ships with the drafts as the audit trail.
- **G2 — Qualifiers survive:** conditions in the spec ("when speakers state them explicitly", "English only", "admin can disable") stay attached to their claims. Dropping a qualifier is an overclaim by subtraction.
- **G3 — No invented reception:** zero usage stats, testimonials, or "customers are raving" before customers exist. Reception claims require reception evidence in the input.

## Steps

1. **Index the spec.** Number what shipped (S1…Sn) and the explicit NOT-list (N1…Nm). These two lists are the whole truth universe: S-lines are claimable, N-lines are blocked, everything else doesn't exist.
2. **Draft external first** — customer value framing built only from S-lines: what it does, for whom, the honest boundaries customers will hit (language, admin control), the price as decided. Omitting an N-line is fine; contradicting one never is.
3. **Draft internal:** what shipped, the NOT-list verbatim (support and sales must know the boundaries better than customers do), known limits, and where feedback goes.
4. **Build the claim-to-spec map:** every capability sentence in both drafts → its S-line. A sentence with no line gets rewritten to one or cut. Marketing verbs may polish a claim; they may not widen it — run each mapped pair through "does the sentence promise anything the line doesn't?"
5. **Gate pass.** Map complete with zero unmapped claims and zero N-list hits (G1), all qualifiers still attached (G2), no reception invented (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
EXTERNAL — customer email / blog
"Meeting summaries, written for you. Every meeting on [our] video calls now ends
with a clear summary — including action items when they're said out loud. English
today. Admins control it workspace-wide. +$10/seat."
INTERNAL — team announcement
Shipped: S1-S6 [list]. NOT in this release (say this to customers who ask): real-time
summaries, non-[our-video] meetings, multi-language, custom templates, mobile.
Known limits: action items only when explicitly stated. Feedback → #ai-summaries.
CLAIM-TO-SPEC MAP
"ends with a clear summary" → S1 · "action items when said out loud" → S3 (qualifier kept)
· "English today" → S2 · "admins control it" → S4 · "+$10/seat" → S6
GATE CHECK: G1 pass (n/n mapped, 0 N-hits) · G2 pass · G3 pass
```

## Hard rules

1. No capability sentence without a spec line, and no sentence touching the NOT-list. The map is mandatory — an announcement without its audit trail doesn't ship.
2. Qualifiers are load-bearing. "When speakers state them explicitly" is the difference between a feature and a lawsuit-shaped promise.
3. Never invent reception, stats, or social proof. The launch announcement earns those claims later or not at all.
4. Internal and external drafts share one truth. The internal draft carries the NOT-list verbatim; the external draft may be silent about it but never contradicts it.

## Limitations

- The drafts are spec-true, not legally reviewed — regulated-industry claims (the legal reviewer persona, once available, or counsel) get the final word.
- Tone is competent-neutral with room for brand energy; deep brand voice is the user's edit — the claim-to-spec map makes that edit safely checkable afterward.
- The skill bounds claims to the spec; it cannot verify the spec itself is true — a spec that overclaims produces a faithfully overclaiming announcement.
- Channel-specific mechanics (subject lines A/B, SEO, social threading) are marketing craft beyond this skill's gate.
