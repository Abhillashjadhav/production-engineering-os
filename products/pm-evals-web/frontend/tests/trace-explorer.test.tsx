// Screen S-3 (journey J-7): Trace Detail — inspect one changed trace's
// per-criterion baseline vs candidate results and evidence fields. The
// component renders the engine's typed `trace_details` only; it computes no
// verdict itself (that lives in the domain layer).
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceExplorer } from "@/components/trace-explorer";
import type { Comparison } from "@/lib/api";

// An engine-shaped fixture exercising all seven per-criterion states in one
// changed trace, plus a second mixed-direction trace. Mirrors the backend
// test_compare.py T-EDGE scenario.
const EDGE: Partial<Comparison> = {
  suite: "s",
  verdict: "HOLD",
  newly_passing_traces: [],
  newly_failing_traces: ["T-EDGE"],
  criteria: [],
  trace_details: [
    {
      trace_id: "T-EDGE",
      direction: "regressed",
      changed: true,
      baseline_label: "baseline case label",
      baseline_notes: "baseline note",
      candidate_label: "candidate case label",
      candidate_notes: "candidate note",
      criteria: [
        { criterion_id: "C-REG", name: "Regression gate", hard_gate: true, baseline_result: "pass", candidate_result: "fail", changed: true, state: "regressed", verdict: "Regressed — hard gate", rationale: "Baseline passed and the candidate fails — a hard-gate regression.", provenance: "both" },
        { criterion_id: "C-UNCH", name: "Stable criterion", hard_gate: false, baseline_result: "pass", candidate_result: "pass", changed: false, state: "unchanged", verdict: "Unchanged — passing", rationale: "Both runs pass this criterion.", provenance: "both" },
        { criterion_id: "C-CONF", name: "Groundedness", hard_gate: false, baseline_result: "pass", candidate_result: "pass", changed: false, state: "conflicting", verdict: "Conflicting definition between runs", rationale: "Both runs recorded the same result, but the hard-gate flag differs between the runs; the definitions conflict.", provenance: "both" },
        { criterion_id: "C-MISS", name: "Baseline-only result", hard_gate: false, baseline_result: "pass", candidate_result: null, changed: false, state: "missing", verdict: "Not comparable", rationale: "Recorded on the baseline run only.", provenance: "baseline_only" },
        { criterion_id: "C-INSUF", name: "Hard gate one side", hard_gate: true, baseline_result: null, candidate_result: "fail", changed: false, state: "insufficient", verdict: "Insufficient", rationale: "This hard gate is recorded on the candidate run only; it cannot be evaluated.", provenance: "candidate_only" },
        { criterion_id: "C-NONE", name: "Never recorded", hard_gate: false, baseline_result: null, candidate_result: null, changed: false, state: "not_evaluated", verdict: "Not evaluated", rationale: "Neither run recorded a result for this criterion on this trace.", provenance: "neither" },
      ],
    },
  ],
} as unknown as Comparison;

const edge = EDGE as Comparison;

function openDetail(traceId: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(traceId) }));
  return screen.getByRole("region", { name: new RegExp(`trace ${traceId} detail`, "i") });
}

describe("TraceExplorer — S-3 Trace Detail (J-7)", () => {
  it("lists changed traces with a direction badge", () => {
    render(<TraceExplorer comparison={edge} />);
    const list = screen.getByRole("list", { name: /changed traces/i });
    expect(within(list).getByText("T-EDGE")).toBeInTheDocument();
    expect(within(list).getByText(/regressed/i)).toBeInTheDocument();
  });

  it("renders EVERY evaluated criterion as a table, not only the flipped ones", () => {
    render(<TraceExplorer comparison={edge} />);
    const detail = openDetail("T-EDGE");
    const table = within(detail).getByRole("table");
    // all six criteria appear as rows, not just the one regression
    for (const id of ["C-REG", "C-UNCH", "C-CONF", "C-MISS", "C-INSUF", "C-NONE"]) {
      expect(within(table).getByText(id)).toBeInTheDocument();
    }
  });

  it("shows baseline and candidate results per criterion, with column headers", () => {
    render(<TraceExplorer comparison={edge} />);
    const detail = openDetail("T-EDGE");
    const table = within(detail).getByRole("table");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/criterion/i),
        expect.stringMatching(/baseline/i),
        expect.stringMatching(/candidate/i),
        expect.stringMatching(/verdict/i),
      ]),
    );
    const regRow = within(table).getByRole("row", { name: /C-REG/ });
    expect(within(regRow).getByText("pass")).toBeInTheDocument();
    expect(within(regRow).getByText("fail")).toBeInTheDocument();
  });

  it("renders each of the seven per-criterion states honestly", () => {
    render(<TraceExplorer comparison={edge} />);
    const table = within(openDetail("T-EDGE")).getByRole("table");
    const row = (id: string) => within(table).getByRole("row", { name: new RegExp(id) });
    expect(within(row("C-REG")).getByText(/regressed/i)).toBeInTheDocument();
    expect(within(row("C-UNCH")).getByText(/unchanged/i)).toBeInTheDocument();
    expect(within(row("C-CONF")).getByText(/conflicting/i)).toBeInTheDocument();
    expect(within(row("C-MISS")).getByText(/not comparable|missing/i)).toBeInTheDocument();
    expect(within(row("C-INSUF")).getByText(/insufficient/i)).toBeInTheDocument();
    expect(within(row("C-NONE")).getByText(/not evaluated/i)).toBeInTheDocument();
  });

  it("shows the trace's evidence fields for both sides", () => {
    render(<TraceExplorer comparison={edge} />);
    const detail = openDetail("T-EDGE");
    expect(within(detail).getByText(/baseline case label/)).toBeInTheDocument();
    expect(within(detail).getByText(/candidate case label/)).toBeInTheDocument();
    expect(within(detail).getByText(/baseline note/)).toBeInTheDocument();
    expect(within(detail).getByText(/candidate note/)).toBeInTheDocument();
  });

  it("renders the empty state when nothing changed", () => {
    const empty = { ...edge, trace_details: [] } as Comparison;
    render(<TraceExplorer comparison={empty} />);
    expect(screen.getByText(/no traces changed between these runs/i)).toBeInTheDocument();
  });

  it("renders a loading state while a comparison is in flight", () => {
    render(<TraceExplorer comparison={null} loading />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("renders an S-3 error when a selected trace has no comparable criteria", () => {
    const broken = {
      ...edge,
      trace_details: [{ ...edge.trace_details[0], criteria: [] }],
    } as Comparison;
    render(<TraceExplorer comparison={broken} />);
    const detail = openDetail("T-EDGE");
    expect(within(detail).getByText(/no comparable criteria/i)).toBeInTheDocument();
  });

  it("narrows the list with the text filter", () => {
    render(<TraceExplorer comparison={edge} />);
    fireEvent.change(screen.getByLabelText(/filter changed traces/i), {
      target: { value: "T-999" },
    });
    expect(screen.getByText(/no changed traces match/i)).toBeInTheDocument();
  });
});
