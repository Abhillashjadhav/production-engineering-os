// Screen S-2 (journey J-6): the comparison dashboard. Every number rendered
// here comes from the engine payload — nothing is computed client-side beyond
// display formatting, so the UI can never invent a metric (PD-V3-07/05).
// Rendering uses plain JSX text nodes; payload strings are never markup.

import type { Comparison, VerdictReason } from "@/lib/api";

const REASON_LABELS: Record<string, string> = {
  hard_gate_regression: "Hard-gate regression",
  incompatible: "Incompatible evidence",
  coverage: "Hard-gate coverage gap",
  guardrail: "Guardrail violation",
  thin_evidence: "Insufficient comparable evidence",
  unevaluable_gate: "Release rule cannot be evaluated",
};

function pct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function signedPct(rate: number): string {
  // exactly zero is unsigned: a "+" prefix would read as strictly positive
  if (rate === 0) return pct(rate);
  return rate > 0 ? `+${pct(rate)}` : pct(rate);
}

function reasonLabel(reason: VerdictReason): string {
  return REASON_LABELS[reason.kind] ?? reason.kind;
}

export function Dashboard({ comparison }: { comparison: Comparison }) {
  return (
    <section aria-labelledby="dashboard-heading" className="dashboard">
      <h2 id="dashboard-heading">Comparison results</h2>

      <div role="region" aria-labelledby="verdict-heading" className="verdict-panel">
        <h3 id="verdict-heading">Release verdict</h3>
        <p className={`verdict verdict-${comparison.verdict.toLowerCase()}`}>
          <strong>{comparison.verdict}</strong>
        </p>
        {comparison.reasons.length > 0 ? (
          <ul className="reasons">
            {comparison.reasons.map((reason) => {
              // criterion_id/trace_ids carry pydantic defaults, so the
              // generated contract type marks them optional
              const criterionId = reason.criterion_id ?? "";
              const traceIds = reason.trace_ids ?? [];
              return (
                <li key={reason.kind + criterionId + reason.detail}>
                  <strong>{reasonLabel(reason)}</strong>
                  {criterionId !== "" && <> — {criterionId}</>}
                  <div>{reason.detail}</div>
                  {traceIds.length > 0 && (
                    <div className="evidence">Evidence traces: {traceIds.join(", ")}</div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p>
            Nothing required got worse and every guardrail passed on the matched
            evidence.
          </p>
        )}
      </div>

      <dl className="summary">
        <div>
          <dt>Suite</dt>
          <dd>{comparison.suite}</dd>
        </div>
        <div>
          <dt>Runs</dt>
          <dd>
            {comparison.baseline_run_id} → {comparison.candidate_run_id}
          </dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>
            {comparison.matched_traces} matched traces
            {comparison.baseline_only_traces.length > 0 &&
              `, ${comparison.baseline_only_traces.length} baseline-only`}
            {comparison.candidate_only_traces.length > 0 &&
              `, ${comparison.candidate_only_traces.length} candidate-only`}
          </dd>
        </div>
        <div>
          <dt>Baseline pass rate</dt>
          <dd>{pct(comparison.baseline_pass_rate)}</dd>
        </div>
        <div>
          <dt>Candidate pass rate</dt>
          <dd>{pct(comparison.candidate_pass_rate)}</dd>
        </div>
        <div>
          <dt>Net change</dt>
          <dd>{signedPct(comparison.net_change)}</dd>
        </div>
        <div>
          <dt>Baseline file digest</dt>
          <dd>
            <code>{comparison.baseline_digest}</code>
          </dd>
        </div>
        <div>
          <dt>Candidate file digest</dt>
          <dd>
            <code>{comparison.candidate_digest}</code>
          </dd>
        </div>
      </dl>

      <table className="criteria">
        <caption>Criterion-level deltas</caption>
        <thead>
          <tr>
            <th scope="col">Criterion</th>
            <th scope="col">Baseline</th>
            <th scope="col">Candidate</th>
            <th scope="col">Delta</th>
            <th scope="col">Newly passing</th>
            <th scope="col">Newly failing</th>
            <th scope="col">Covered traces</th>
          </tr>
        </thead>
        <tbody>
          {comparison.criteria.map((criterion) => (
            <tr
              key={criterion.criterion_id}
              className={criterion.newly_failing.length > 0 ? "regressed-row" : undefined}
            >
              <th scope="row">
                {criterion.criterion_id}
                {criterion.hard_gate && <span className="hard-gate-badge"> hard gate</span>}
                <div className="criterion-description">{criterion.description}</div>
              </th>
              <td>{pct(criterion.baseline_pass_rate)}</td>
              <td>{pct(criterion.candidate_pass_rate)}</td>
              <td>{signedPct(criterion.delta)}</td>
              <td>{criterion.newly_passing.length}</td>
              <td>{criterion.newly_failing.length}</td>
              <td>{criterion.covered_traces}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
