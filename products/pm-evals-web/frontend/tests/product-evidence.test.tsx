import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductEvidence } from "@/components/product-evidence";
import type { MonitoringOverview, ProductHealth } from "@/lib/api";

type Metric = NonNullable<MonitoringOverview["detection_metrics"]>[number];

const PRODUCT: ProductHealth = {
  product_id: "linkedin", display_name: "LinkedIn", version: "v1", environment: "production",
  latest_run_id: "run-1", observed_at: "2026-09-05T12:00:00Z", health: "FAILING",
  is_stale: false, freshness_sla_seconds: 3600, pass_count: 2, fail_count: 1,
  blocked_count: 0, layers: [], concerns: [], delivery_outcome: "COMPLETED_WITH_WARNINGS",
  source_facts: [{
    contract: "candidate-acceptance", subject_id: "candidate-1", cycle: 0,
    recorded_status: "PASS", observed_status: "FAIL", mode: "diagnostic", value: 0,
    reason_codes: ["CLAIM_SUPPORT_MISSING"],
    evidence_refs: [{ uri: "artifact://linkedin/result", sha256: `sha256:${"a".repeat(64)}` }],
  }, {
    contract: "candidate-acceptance", subject_id: "candidate-1", cycle: 1,
    recorded_status: "PASS", observed_status: "PASS", mode: "enforce", value: 1,
    reason_codes: [], evidence_refs: [],
  }],
};

function metric(layer: Metric["layer"], detected: number, scope: Metric["evidence_scope"] = "TEST"): Metric {
  return {
    product_id: "linkedin", environment: "production", dataset_version: "review-v1",
    evidence_scope: scope, layer, reviewed_cases: 10, silent_failures: 10,
    detected_silent_failures: detected, missed_silent_failures: 10 - detected,
    silent_failure_recall: detected / 10,
    status: detected > 9 ? "OBSERVED_ABOVE_TARGET" : "BELOW_TARGET",
  };
}

describe("ProductEvidence", () => {
  it("keeps delivery, advisory failures, candidate repair cycles, and evidence distinct", () => {
    render(<ProductEvidence products={[PRODUCT]} metrics={[]} />);
    const summary = screen.getByText(/LinkedIn — Delivery: COMPLETED_WITH_WARNINGS/);
    fireEvent.click(summary);
    const table = screen.getByRole("table", { name: /individual checks/i });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("FAIL")).toBeInTheDocument();
    expect(within(rows[1]).getByText("PASS")).toBeInTheDocument();
    expect(within(rows[1]).getByText("diagnostic")).toBeInTheDocument();
    expect(within(rows[1]).getByText("CLAIM_SUPPORT_MISSING")).toBeInTheDocument();
    expect(within(rows[1]).getAllByText("0")).toHaveLength(2);
    expect(within(rows[2]).getByText("enforce")).toBeInTheDocument();
    fireEvent.click(within(rows[1]).getByText("Evidence digest"));
    expect(within(rows[1]).getByText(`sha256:${"a".repeat(64)}`)).toBeVisible();
    expect(screen.getByText(/all three layers remain unproven/i)).toBeInTheDocument();
  });

  it("shows each layer independently and keeps test evidence separate from production", () => {
    render(<ProductEvidence products={[PRODUCT]} metrics={[
      metric("TOOL_TRAJECTORY", 9), metric("SYSTEM", 10), metric("OUTPUT", 10),
      { ...metric("TOOL_TRAJECTORY", 0, "PRODUCTION"), reviewed_cases: 0, silent_failures: 0,
        detected_silent_failures: 0, missed_silent_failures: 0, silent_failure_recall: null, status: "UNPROVEN" },
    ]} />);
    const table = screen.getByRole("table", { name: /results by product/i });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(5);
    expect(within(rows[1]).getByText("TOOL_TRAJECTORY")).toBeInTheDocument();
    expect(within(rows[1]).getByText("90.0%")).toBeInTheDocument();
    expect(within(rows[1]).getByText("below target")).toBeInTheDocument();
    expect(within(rows[2]).getByText("SYSTEM")).toBeInTheDocument();
    expect(within(rows[3]).getByText("OUTPUT")).toBeInTheDocument();
    expect(within(rows[4]).getByText("PRODUCTION")).toBeInTheDocument();
    expect(within(rows[4]).getAllByText("unproven")).toHaveLength(2);
    expect(within(table).queryByText(/96\.7%/)).not.toBeInTheDocument();
  });

  it("shows no reviews for a selected environment instead of an empty metrics table", () => {
    render(<ProductEvidence products={[{ ...PRODUCT, environment: "staging" }]} metrics={[
      metric("OUTPUT", 10),
    ]} />);
    expect(screen.getByText(/no independent failure reviews recorded/i)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /results by product/i })).not.toBeInTheDocument();
  });
});
