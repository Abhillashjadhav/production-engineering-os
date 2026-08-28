---
name: drift-monitor-designer
description: "Iterate-stage skill: designs production drift monitoring for a shipped AI feature — every monitored signal carrying a threshold and a named response action. Use when a live feature needs watching — 'design drift monitoring for the summarizer', 'how do we know when it degrades in production', 'what do we watch now that it shipped' — or when /pm routes such a request here. Do NOT use for per-request guardrails (guardrail-designer), for pre-ship change gating (regression-gatekeeper), for building the dashboards themselves, or for drift definitions."
argument-hint: "<the shipped feature + volume + available plumbing (logs, feedback events, judge-sample capacity) + quality dimensions from its eval>"
---

# Drift Monitor Designer

Production quality decays quietly. A monitor is a signal with a threshold and a hand that moves when it's crossed — "watch quality and alert if it drops" is anxiety, not monitoring.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Threshold + named action, every signal:** each signal carries a threshold (numeric with a stated basis, or a labeled placeholder with the baseline-collection step that will set it) and a named response action with its route (pull a judge sample, flip the rollback posture, recalibrate). Thresholdless watching or actionless alerting fails.
- **G2 — Plumbing-bounded, cost-layered:** signals use only the stated instrumentation, arranged cheap-to-expensive: continuous proxies (edits, deletes, thumbs) triage; scheduled judge runs against the eval's gates are the ground truth; input-distribution signals watch the upstream cause. Proxies never substitute for ground truth, and their biases are stated (12% feedback = self-selected sample).
- **G3 — Alert hygiene:** every signal names its expected false-positive source and its damping rule (consecutive windows, not single spikes). No invented baselines — unknown baselines get a collection window, not a made-up number.

## Steps

1. **Bank the surface:** volume, plumbing (what's logged, what users emit, judge-sample capacity), the eval's quality dimensions (gates and rubric — the monitor watches for regressions against exactly these), and whether a rollback path still exists.
2. **Layer the signals.** Continuous proxies from existing events (edit distance, delete rate, thumbs-down rate — biased and lagging, said so) · scheduled ground truth (the weekly judge run at stated capacity, scoring the eval's gate-failure rate) · input drift (length, language, source mix — degradation's usual upstream cause).
3. **Set thresholds honestly.** Where baseline weeks exist, thresholds are deltas over baseline; where not, the first N weeks are the stated baseline-collection window and thresholds are labeled placeholders until it closes. Absolute numbers with no basis don't ship.
4. **Name every action with its route:** proxy breach → judge sample of M cases within 24h (triage confirms or clears) · judge-run gate-failure above threshold → regression posture: rollback-flag decision with its owner · confirmed drift → failure-to-eval-capture encodes the new failures; proxy-vs-judge divergence → judge-calibration-auditor. Each action has an owner role from the stated context.
5. **Write the damping rules:** known benign variations (holidays, long-meeting weeks) and the consecutive-window requirement per signal — an alert that fires weekly gets ignored by week three, which is worse than no alert.
6. **Gate pass.** Every signal thresholded + actioned (G1), plumbing-real and layered (G2), hygiene present with no invented baselines (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
DRIFT MONITOR: AI meeting summaries (9,000/wk · judge capacity 150/wk · rollback flag live)
CONTINUOUS (proxies — triage only)
S1 summary delete/regenerate rate — baseline: collect weeks 1-2 → threshold +[X]%
   over baseline, 2 consecutive weeks — ACTION: 50-case judge sample within 24h
   (owner: PM) — FP source: holiday volume dips → damped by consecutive-window rule
S2 thumbs-down rate [12% feedback: self-selected, lagging — stated] — same pattern
SCHEDULED GROUND TRUTH
S3 weekly judge run, 150 sampled summaries vs eval gates — threshold: gate-failure
   rate >2x launch-month rate — ACTION: rollback-posture decision (owner: eng lead)
   + failing cases → failure-to-eval-capture
INPUT DRIFT
S4 meeting-length / language mix vs launch distribution — threshold: [labeled] —
   ACTION: investigate upstream before blaming the model
CROSS-CHECK: S2 vs S3 divergence → judge-calibration-auditor.
GATE CHECK: G1 pass (4/4 thresholded+actioned) · G2 pass · G3 pass
```

## Hard rules

1. No signal without its threshold and its named, routed action. A monitor nobody answers is a log.
2. Proxies triage; judge runs decide. A thumbs-based alarm can page someone, but only the ground-truth sample can indict the model.
3. Baselines are measured or scheduled for measurement — never invented. A placeholder threshold carries the date its baseline window closes.
4. Every alert has damping and a named false-positive source. Undamped alerts train people to ignore the monitor.

## Limitations

- The design specifies signals, thresholds, and routes; wiring the queries, samples, and pages is engineering work it scopes.
- Proxy biases are stated but not removed — self-selected feedback under-represents silent churners; the judge sample is the corrective, at its stated capacity.
- Drift detection lags by its window; catastrophic same-day failures are guardrail-designer territory (per-request), not weekly monitoring.
- Thresholds decay as the product changes; the design includes its own revisit trigger (major feature or model change → re-baseline) but can't enforce it.
