"use client";

// Screen S-3 (journey J-7): the changed-trace explorer. The table and every
// per-trace detail derive from the engine payload's newly_passing/newly_failing
// lists — no client-side re-comparison. If a changed trace ever lacks
// criterion-level evidence (an engine-invariant violation), the detail says so
// honestly instead of rendering silence (S-3 error state).

import { useId, useState } from "react";

import type { Comparison } from "@/lib/api";

type Direction = "improved" | "regressed";

interface ChangedTrace {
  traceId: string;
  direction: Direction;
}

function changedTraces(comparison: Comparison): ChangedTrace[] {
  const improved: ChangedTrace[] = comparison.newly_passing_traces.map((traceId) => ({
    traceId,
    direction: "improved",
  }));
  const regressed: ChangedTrace[] = comparison.newly_failing_traces.map((traceId) => ({
    traceId,
    direction: "regressed",
  }));
  return [...improved, ...regressed].sort((a, b) => a.traceId.localeCompare(b.traceId));
}

interface CriterionFlip {
  criterionId: string;
  hardGate: boolean;
  flip: "now passes" | "now fails";
}

function flipsFor(comparison: Comparison, traceId: string): CriterionFlip[] {
  const flips: CriterionFlip[] = [];
  for (const criterion of comparison.criteria) {
    if (criterion.newly_passing.includes(traceId)) {
      flips.push({
        criterionId: criterion.criterion_id,
        hardGate: criterion.hard_gate,
        flip: "now passes",
      });
    }
    if (criterion.newly_failing.includes(traceId)) {
      flips.push({
        criterionId: criterion.criterion_id,
        hardGate: criterion.hard_gate,
        flip: "now fails",
      });
    }
  }
  return flips;
}

export function TraceExplorer({ comparison }: { comparison: Comparison }) {
  const filterInputId = useId();
  const directionSelectId = useId();
  const [filter, setFilter] = useState("");
  const [direction, setDirection] = useState<"all" | Direction>("all");
  const [selectedTrace, setSelectedTrace] = useState<string | null>(null);

  const all = changedTraces(comparison);
  if (all.length === 0) {
    return (
      <section aria-labelledby="traces-heading">
        <h2 id="traces-heading">Changed traces</h2>
        <p>No traces changed between these runs.</p>
      </section>
    );
  }

  const visible = all.filter(
    (trace) =>
      trace.traceId.toLowerCase().includes(filter.toLowerCase()) &&
      (direction === "all" || trace.direction === direction),
  );
  const selectedFlips = selectedTrace !== null ? flipsFor(comparison, selectedTrace) : [];

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
            onChange={(e) => setDirection(e.target.value as "all" | Direction)}
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
            <li key={trace.traceId}>
              <button
                type="button"
                onClick={() =>
                  setSelectedTrace((current) =>
                    current === trace.traceId ? null : trace.traceId,
                  )
                }
                aria-expanded={selectedTrace === trace.traceId}
              >
                {trace.traceId}
              </button>{" "}
              <span className={`direction direction-${trace.direction}`}>{trace.direction}</span>
            </li>
          ))}
        </ul>
      )}

      {selectedTrace !== null && (
        <div role="region" aria-label={`Trace ${selectedTrace} detail`} className="trace-detail">
          <h3>{selectedTrace}</h3>
          {selectedFlips.length > 0 ? (
            <ul>
              {selectedFlips.map((flip) => (
                <li key={flip.criterionId + flip.flip}>
                  <strong>{flip.criterionId}</strong>
                  {flip.hardGate && <span className="hard-gate-badge"> hard gate</span>} —{" "}
                  {flip.flip}
                </li>
              ))}
            </ul>
          ) : (
            <p className="trace-detail-error">
              No criterion-level evidence found for this trace — this should not
              happen; re-run the comparison and report it if it persists.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
