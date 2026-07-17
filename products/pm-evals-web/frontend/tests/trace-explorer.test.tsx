// Screen S-3 (journey J-7): the changed-trace table with filtering and
// per-trace criterion-level detail, derived entirely from the engine payload.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceExplorer } from "@/components/trace-explorer";
import type { Comparison } from "@/lib/api";

import regressionJson from "./fixtures/comparison_regression.json";

const regression = regressionJson as unknown as Comparison;

describe("TraceExplorer — changed traces (J-7)", () => {
  it("lists every changed trace with its direction", () => {
    render(<TraceExplorer comparison={regression} />);
    // golden: T-003 improved; T-001, T-002, T-006 regressed
    const list = screen.getByRole("list", { name: /changed traces/i });
    expect(within(list).getByText("T-003")).toBeInTheDocument();
    expect(within(list).getByText("T-006")).toBeInTheDocument();
    expect(within(list).getAllByText(/regressed/i)).toHaveLength(3);
    expect(within(list).getAllByText(/improved/i)).toHaveLength(1);
  });

  it("narrows the table with the text filter", () => {
    render(<TraceExplorer comparison={regression} />);
    fireEvent.change(screen.getByLabelText(/filter changed traces/i), {
      target: { value: "T-006" },
    });
    const list = screen.getByRole("list", { name: /changed traces/i });
    expect(within(list).getByText("T-006")).toBeInTheDocument();
    expect(within(list).queryByText("T-003")).not.toBeInTheDocument();
  });

  it("narrows the table with the direction filter", () => {
    render(<TraceExplorer comparison={regression} />);
    fireEvent.change(screen.getByLabelText(/show/i), { target: { value: "improved" } });
    const list = screen.getByRole("list", { name: /changed traces/i });
    expect(within(list).getByText("T-003")).toBeInTheDocument();
    expect(within(list).queryByText("T-006")).not.toBeInTheDocument();
  });

  it("says when no changed trace matches the filter", () => {
    render(<TraceExplorer comparison={regression} />);
    fireEvent.change(screen.getByLabelText(/filter changed traces/i), {
      target: { value: "T-999" },
    });
    expect(screen.getByText(/no changed traces match/i)).toBeInTheDocument();
  });

  it("opens a per-trace detail with criterion-level flips (keyboard-reachable)", () => {
    render(<TraceExplorer comparison={regression} />);
    fireEvent.click(screen.getByRole("button", { name: /T-006/ }));
    const detail = screen.getByRole("region", { name: /trace T-006 detail/i });
    expect(within(detail).getByText("C-GROUNDED")).toBeInTheDocument();
    expect(within(detail).getByText(/now fails/i)).toBeInTheDocument();
    expect(within(detail).getByText(/hard gate/i)).toBeInTheDocument();
  });

  it("shows an improved trace's flips as now-passing", () => {
    render(<TraceExplorer comparison={regression} />);
    fireEvent.click(screen.getByRole("button", { name: /T-003/ }));
    const detail = screen.getByRole("region", { name: /trace T-003 detail/i });
    expect(within(detail).getByText("C-ACCURACY")).toBeInTheDocument();
    expect(within(detail).getByText(/now passes/i)).toBeInTheDocument();
  });

  it("closes the detail when the filter excludes the selected trace", () => {
    // PR 8's reviewer noted the detail panel outliving its filtered-out row —
    // a detail must never describe a trace the table no longer shows.
    render(<TraceExplorer comparison={regression} />);
    fireEvent.click(screen.getByRole("button", { name: /T-006/ }));
    expect(screen.getByRole("region", { name: /trace T-006 detail/i })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/filter changed traces/i), {
      target: { value: "T-003" },
    });
    expect(
      screen.queryByRole("region", { name: /trace T-006 detail/i }),
    ).not.toBeInTheDocument();
  });

  it("renders the empty state when nothing changed between the runs", () => {
    const unchanged = {
      ...regression,
      newly_passing_traces: [],
      newly_failing_traces: [],
    } as Comparison;
    render(<TraceExplorer comparison={unchanged} />);
    expect(screen.getByText(/no traces changed between these runs/i)).toBeInTheDocument();
  });

  it("fails honestly when a changed trace has no criterion-level evidence (S-3 error state)", () => {
    // The engine always provides per-criterion evidence for changed traces —
    // if that invariant ever breaks, the UI must say so, not render silence.
    const broken = {
      ...regression,
      newly_failing_traces: [...regression.newly_failing_traces, "T-GHOST"],
    } as Comparison;
    render(<TraceExplorer comparison={broken} />);
    fireEvent.click(screen.getByRole("button", { name: /T-GHOST/ }));
    const detail = screen.getByRole("region", { name: /trace T-GHOST detail/i });
    expect(
      within(detail).getByText(/no criterion-level evidence found for this trace/i),
    ).toBeInTheDocument();
  });
});
