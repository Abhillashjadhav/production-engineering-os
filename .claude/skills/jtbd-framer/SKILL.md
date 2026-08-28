---
name: jtbd-framer
description: "Discovery-stage skill: reframes a feature idea or feature request into jobs-to-be-done statements containing zero solution language. Use when the user wants the underlying job behind a feature — 'frame this as JTBD', 'what job is this feature hired for', 'what are users really trying to get done', 'rewrite these requests as jobs' — or when /pm routes such a request here. Do NOT use for explaining JTBD theory, writing PRDs (Build stage), synthesizing interviews (interview-synthesizer — its patterns can feed this skill), or prioritizing feature lists."
argument-hint: "<the feature idea + who it's for / the context you have>"
---

# JTBD Framer

A feature idea in, the jobs behind it out — with the solution scrubbed from every statement, because a job that names the feature is just the feature wearing a costume.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Zero solution language:** no bracketed segment of any job statement contains the feature name or its mechanics, product/brand names, technology nouns (AI, app, button, dashboard, algorithm, integration), or UI verbs (click, tap, toggle, open). The check is a mechanical scan of every bracket against these classes.
- **G2 — Canonical form:** every statement reads "When [situation], I want to [motivation], so I can [expected outcome]" — three brackets, each doing its own work (no outcome restated as motivation).
- **G3 — Traceability:** every statement derives from the provided idea/context. No invented personas, segments, or circumstances that appear from nowhere.

## Steps

1. **Strip the idea to its actors and moment.** Who is the person, in what recurring situation, and what progress are they struggling to make? If the input has no who/when at all, ask one question — don't invent a persona.
2. **Ladder down from feature to job.** Ask "what does this feature let them stop doing / stop worrying about?" until the answer contains no technology. The feature is one candidate hire for the job, never the job.
3. **Draft 2–4 statements** in canonical form. Fewer, sharper jobs beat a laundry list — one feature rarely serves five distinct jobs.
4. **Tag each dimension:** functional / emotional / social. Push for at least one non-functional dimension — features are usually hired for the anxiety they remove, not just the task they complete; if genuinely none surfaces, say so rather than manufacturing one.
5. **Name the current hires.** Per job, what does the person use today (tools, workarounds, doing nothing)? That's the real competition the feature must beat.
6. **Gate pass.** Scan every bracket for solution language (G1), check form (G2) and traceability (G3). Rewrite violators and re-scan; maximum 2 repair loops, then report the failure instead of the output.

## Output format

```
FEATURE AS PITCHED: <one line, solution language allowed here only>
JOBS
1. When [a prospect agrees to a demo on a call], I want to [lock the time before their
   interest cools], so I can [keep the deal moving]. — functional
   Currently hired: email back-and-forth · manual calendar comparison
2. ... — social
GATE CHECK: G1 pass (0 solution terms in n brackets) · G2 pass · G3 pass
```

## Hard rules

1. Solution language never appears inside a job statement's brackets. The feature name may appear only in the "feature as pitched" header line.
2. Never invent research. Job statements here are hypotheses derived from the stated context — label them as such; validating them is interview work, not framing work.
3. Never pad the job list. If the feature honestly serves one job, output one job and say so.
4. The "so I can" outcome must be a change in the person's life or work, not a product behavior ("so I can book in one click" fails; "so I can keep the deal moving" passes).

## Limitations

- Statements are well-formed hypotheses, not validated jobs — validation needs interviews (interview-synthesizer output is the natural evidence source).
- The solution-language scan catches the defined term classes; a sufficiently abstract solution noun ("assistant") can slip past — the reader should sanity-check brackets for smuggled products.
- Emotional/social tags are judgment calls from context, not measured user data.
- Framing quality degrades when the input has no who/when context; the skill asks rather than assumes, which costs a round-trip.
