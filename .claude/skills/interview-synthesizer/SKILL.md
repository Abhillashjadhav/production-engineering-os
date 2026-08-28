---
name: interview-synthesizer
description: "Discovery-stage skill: turns user-interview transcripts into evidence-cited patterns. Use when the user provides one or more interview transcripts, discovery-call notes, or user-research conversations and asks what patterns, themes, or learnings they contain — 'synthesize these interviews', 'what patterns are in these transcripts', 'what did we learn from these calls' — or when /pm routes a Discovery request here. Do NOT use for lists of feedback items or support tickets (feedback-pattern-miner's job), for summarizing a single meeting, or to invent personas or findings when no transcript data is provided — with no data it refuses."
argument-hint: "<paste 1+ interview transcripts or notes>"
---

# Interview Synthesizer

Transcripts in, patterns out — every pattern earned by verbatim evidence, or it doesn't ship.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Evidence floor:** every pattern cites ≥2 verbatim quotes. From ≥2 different transcripts when more than one exists; a single-transcript pattern is labeled `single-source`.
- **G2 — Zero invented quotes:** every quoted string matches the source transcript character-for-character (contiguous span; trimming only at the ends). The gate check is mechanical: search each output quote in the input text — any miss fails the gate.
- **G3 — Attribution:** every quote carries transcript + speaker (e.g. `[T2-Marco]`).

## Steps

1. **Index.** Label each transcript (T1, T2, …) and each speaker. If the user supplied zero transcripts, stop: ask for them — never synthesize from nothing.
2. **Extract candidates.** Read across transcripts for repeated pains, workarounds, desires, and objections. A candidate is anything mentioned by ≥2 sources — or a strong single-source signal, tracked separately.
3. **Evidence pass.** For each candidate, collect exact quote spans (≤40 words each — quote minimally, cite precisely). Copy, never retype from memory.
4. **Demote or drop.** Candidates that can't produce 2 verbatim quotes become `Hypothesis (insufficient evidence: N quote)` at the bottom of the output, or are dropped. Never pad evidence to promote a favorite.
5. **Gate pass.** Run G1–G3 on the draft: substring-match every quote against the inputs, count citations per pattern, check attributions. Fix violations and re-run; maximum 2 repair loops, then report the failure instead of the output.
6. **Deliver.** Patterns ranked by evidence strength (n of N transcripts), each with quotes, attributions, and any contradicting evidence found — contradictions are reported, not smoothed over.

## Output format

```
PATTERNS (from N transcripts)
1. <pattern name> — n/N transcripts
   "<verbatim quote>" [T1-Speaker]
   "<verbatim quote>" [T2-Speaker]
   Contradicting evidence: <quote + tag, or "none found">

HYPOTHESES (insufficient evidence — do not act without more interviews)
- <candidate> — 1 quote [T1-Speaker]
GATE CHECK: G1 pass · G2 pass (all quotes matched at source) · G3 pass
```

## Hard rules

1. Nothing inside quotation marks may be paraphrased, cleaned up, or reconstructed from memory. Verbatim means verbatim — fix grammar outside the quotes, never inside.
2. Never merge words from two speakers or two locations in a transcript into one quote. One quote = one contiguous span.
3. A pattern below the 2-quote floor is demoted or dropped, never padded with a near-miss quote.
4. Contradicting evidence found during the evidence pass must appear in the output. Suppressing counter-evidence is a gate-level failure even though no gate mechanically catches it.

## Limitations

- Patterns reflect only the transcripts provided; 2 quotes is an evidence floor, not statistical significance — say so when N is small.
- The verbatim gate catches invented quotes, not invented interpretations; the reader should check that pattern names fairly describe their quotes.
- Speaker attribution depends on the transcript labeling speakers; unlabeled sources are tagged `[T1-unattributed]`.
- Works on text the user pastes; it does not fetch recordings or external research tools.
