"use client";

// Screen S-3 (journey J-7): Trace Detail. Inspect one changed trace's
// per-criterion baseline vs candidate results and evidence fields. The
// component renders the engine's typed `trace_details` verbatim — every state,
// verdict, and rationale is computed in the domain layer (compare.py); the UI
// never re-derives an outcome.

import { useId, useState } from "react";

import type { Comparison, CriterionCell, TraceComparison } from "@/lib/api";

type DirectionFilter = "all" | "improved" | "regressed";

function matchesDirection(trace: TraceComparison, filter: DirectionFilter): boolean {
  if (filter === "all") return true;
  if (filter === "improved") return trace.direction === "improved" || trace.direction === "mixed";
  return trace.direction === "regressed" || trace.direction === "mixed";
}

function resultText(result: CriterionCell["baseline_result"]): string {
  return result === null ? "—" : result;
}

export function TraceExplorer({
  comparison,
  loading = false,
}: {
  comparison: Comparison | null;
  loading?: boolean;
}) {
  const filterInputId = useId();
  const directionSelectId = useId();
  const [filter, setFilter] = useState("");
  const [direction, setDirection] = useState<DirectionFilter>("all");
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);

  if (loading) {
    return (
      <section aria-labelledby="traces-heading">
        <h2 id="traces-heading">Changed traces</h2>
        <p role="status" aria-live="polite">
          Loading trace comparison…
        </p>
      </section>
    );
  }

  const details = comparison?.trace_details ?? [];
  if (details.length === 0) {
    return (
      <section aria-labelledby="traces-heading">
        <h2 id="traces-heading">Changed traces</h2>
        <p>No traces changed between these runs.</p>
      </section>
    );
  }

  const visible = details.filter(
    (trace) =>
      trace.trace_id.toLowerCase().includes(filter.toLowerCase()) &&
      matchesDirection(trace, direction),
  );
  // the detail must never describe a trace the table no longer shows
  const selected =
    selectedTrace !== null && visible.some((trace) => trace.trace_id === selectedTrace)
      ? (details.find((trace) => trace.trace_id === selectedTrace) ?? null)
      : null;

  return (
    <section aria-labelledby="traces-heading">
      <h2 id="traces-heading">Changed traces</h2>
      <div className="trace-filters">
        <div>
          <label htmlFor={filterInputId}>Filter changed traces</label>
          <input
            id={filterInputId}
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={directionSelectId}>Show</label>
          <select
            id={directionSelectId}
            value={direction}
            onChange={(e) => setDirection(e.target.value as DirectionFilter)}
          >
            <option value="all">All</option>
            <option value="improved">Improved</option>
            <option value="regressed">Regressed</option>
          </select>
        </div>
      </div>

      {visible.length === 0 ? (
        <p>No changed traces match the filter.</p>
      ) : (
        <ul aria-label="Changed traces" className="trace-list">
          {visible.map((trace) => (
            <li key={trace.trace_id}>
              <button
                type="button"
                onClick={() =>
                  setSelectedTrace((current) =>
                    current === trace.trace_id ? null : trace.trace_id,
                  )
                }
                aria-expanded={selectedTrace === trace.trace_id}
                aria-controls={
                  selectedTrace === trace.trace_id
                    ? `trace-detail-${trace.trace_id}`
                    : undefined
                }
              >
                {trace.trace_id}
              </button>{" "}
              <span className={`direction direction-${trace.direction}`}>{trace.direction}</span>
            </li>
          ))}
        </ul>
      )}

      {selected !== null && <TraceDetail trace={selected} />}
    </section>
  );
}

function TraceDetail({ trace }: { trace: TraceComparison }) {
  return (
    <div
      id={`trace-detail-${trace.trace_id}`}
      role="region"
      aria-label={`Trace ${trace.trace_id} detail`}
      className="trace-detail"
    >
      <h3>{trace.trace_id}</h3>
      <dl className="trace-evidence">
        <div>
          <dt>Baseline label</dt>
          <dd>{trace.baseline_label || "—"}</dd>
        </div>
        <div>
          <dt>Baseline notes</dt>
          <dd>{trace.baseline_notes || "—"}</dd>
        </div>
        <div>
          <dt>Candidate label</dt>
          <dd>{trace.candidate_label || "—"}</dd>
        </div>
        <div>
          <dt>Candidate notes</dt>
          <dd>{trace.candidate_notes || "—"}</dd>
        </div>
      </dl>
      {trace.criteria.length === 0 ? (
        <p className="trace-detail-error" role="alert">
          This trace has no comparable criteria — this should not happen; re-run the comparison
          and report it if it persists.
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption>Per-criterion comparison for {trace.trace_id}</caption>
            <thead>
              <tr>
                <th scope="col">Criterion</th>
                <th scope="col">Baseline</th>
                <th scope="col">Candidate</th>
                <th scope="col">Verdict</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {trace.criteria.map((cell) => (
                <tr key={cell.criterion_id} className={`cell-${cell.state}`}>
                  <th scope="row">
                    <span className="criterion-id">{cell.criterion_id}</span>
                    {cell.hard_gate && <span className="hard-gate-badge"> hard gate</span>}
                    <span className="criterion-name">{cell.name}</span>
                  </th>
                  <td data-result={cell.baseline_result ?? "none"}>
                    {resultText(cell.baseline_result)}
                  </td>
                  <td data-result={cell.candidate_result ?? "none"}>
                    {resultText(cell.candidate_result)}
                  </td>
                  <td>{cell.verdict}</td>
                  <td>{cell.rationale}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
