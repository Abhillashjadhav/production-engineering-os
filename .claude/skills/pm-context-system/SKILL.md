---
name: pm-context-system
description: "Build-stage skill: watches a working session and proposes one-line memory captures — never an interview — building a four-file project context (INDEX, STAKEHOLDERS, DECISIONS, STATE) that compounds across sessions. Use when the user asks for persistent project memory — 'set up project memory', 'make Claude remember my stakeholders', 'you keep forgetting my project' — and proactively whenever a decision, stakeholder fact, or state change worth keeping surfaces in conversation. Do NOT use for one-off summaries, for auditing an existing context file (context-auditor), or for questions about whether Claude remembers past chats."
argument-hint: "<nothing needed — it watches; or say 'set up project memory' / 'update context'>"
---

# PM Context System

Memory built one approved line at a time. The moment something worth keeping happens, one proposal — never a questionnaire, never a silent write.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Single-line proposal form:** every capture proposal is exactly one line: `Log to memory: "<fact/decision + why>" — yes/edit/skip`. Multi-line proposals, batched questions, or any interview fail the gate.
- **G2 — Consent before write:** nothing is written to any file without a `yes` or `edit` on its specific proposal. Silent writes fail; a `skip` is final — that item is never re-proposed.
- **G3 — Event-driven, deduplicated:** proposals fire on actual session events (a decision lands, a stakeholder fact surfaces, state changes) and never re-propose what's already logged. The end-of-session sweep proposes only the unlogged remainder.

## Steps

1. **Watch.** During any session, when a decision is made, a stakeholder fact surfaces, or project state changes, emit the one-line proposal tied to that specific event — then continue the task. Nothing noteworthy → total silence; an empty check contributes zero lines.
2. **Scaffold on first yes, silently.** If `context/` doesn't exist when a proposal is approved, create it without announcement: `INDEX.md` (read order + one-line file summaries), `STAKEHOLDERS.md`, `DECISIONS.md` (append-only), `STATE.md`. Write the approved entry where it belongs; add one pointer line to CLAUDE.md: "At session start, read context/INDEX.md first."
3. **Read order at session start:** INDEX → STATE → the other two only when the task touches a person or reopens a decision. Progressive disclosure; never bulk-load all four.
4. **Sweep on request or session end.** "Update context" → one pass over the session for unlogged decisions/state changes; each gets its own one-line proposal. Already-logged items are skipped — the sweep is a diff, not a replay.
5. **Maintain when touching files:** merge duplicate entries (keep newer framing); STATE items idle 30+ days → propose archiving (never silently delete); contradicted entries → flag `[STALE?]` and ask; DECISIONS.md corrections are new entries referencing the old, never edits.

## Output format

```
(mid-session, a decision just landed)
Log to memory: "API pricing: usage-based over flat — flat penalizes low-volume pilots" — yes/edit/skip

(after "yes", first time only — silent scaffold, then:)
Logged to context/DECISIONS.md.

(session end, "update context")
Log to memory: "STATE: billing migration blocked on legal review of usage terms" — yes/edit/skip
(nothing else — the pricing decision above is already logged)
```

## Hard rules

1. Never interview. Five questions up front is the failure mode this skill replaces — one proposal per event, tied to what just happened, always skippable.
2. Never write without consent, and never re-propose a skip. Trust in the memory system is the product; one silent write ends it.
3. Never fabricate memory: entries record what was actually said this session — no inferred stakeholder opinions, no filled-in rationale the user didn't give (an `edit` exists for exactly that).
4. DECISIONS.md is append-only. History that can be rewritten isn't history.

## Limitations

- Memory lives in repo files; it persists per project and syncs only via git — nothing crosses machines or projects on its own.
- A session must read the files for memory to work; the CLAUDE.md pointer makes that reliable in Claude Code, best-effort elsewhere.
- Quality depends on the ritual actually running — skipped sessions create silent gaps, not errors.
- STAKEHOLDERS.md holds professional context only: no health, private-life, or anything a stakeholder wouldn't expect written down — such proposals are never made.
