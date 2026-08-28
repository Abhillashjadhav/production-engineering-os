import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MonitoringDashboard } from "@/components/monitoring-dashboard";
import type { MonitoringOverview } from "@/lib/api";

const OVERVIEW: MonitoringOverview = {
  generated_at: "2026-08-28T12:00:00Z",
  mode: "PLANTED_DEMO",
  attribution_metrics: {
    correctly_localized_rate: 1,
    attribution_coverage: 1,
    false_attribution_rate: 0,
    known_cause_sample_size: 1,
    production_adjudicated_sample_size: 0,
    false_attribution_target: 0.02,
    guardrail_proven: false,
    label: "One planted controlled-replay case",
  },
  products: [
    {
      product_id: "dream-job-agent",
      display_name: "Dream Job Agent",
      version: "v2",
      environment: "production",
      latest_run_id: "dream-run",
      observed_at: "2026-08-28T12:00:00Z",
      health: "FAILING",
      pass_count: 3,
      fail_count: 2,
      blocked_count: 0,
      layers: [{ name: "RETRIEVAL_TOOL", health: "FAILING", pass_count: 0, fail_count: 1, blocked_count: 0 }],
      concerns: [{ name: "INVARIANT", health: "FAILING", pass_count: 0, fail_count: 1, blocked_count: 0 }],
    },
    {
      product_id: "linkedin-research-os",
      display_name: "LinkedIn Research OS",
      version: "v2",
      environment: "production",
      latest_run_id: "linkedin-run",
      observed_at: "2026-08-28T10:00:00Z",
      health: "HEALTHY",
      pass_count: 5,
      fail_count: 0,
      blocked_count: 0,
      layers: [{ name: "OUTPUT", health: "HEALTHY", pass_count: 1, fail_count: 0, blocked_count: 0 }],
      concerns: [{ name: "QUALITY", health: "HEALTHY", pass_count: 1, fail_count: 0, blocked_count: 0 }],
    },
  ],
  incidents: [
    {
      incident_id: "dream-run:source-linkedin-coverage",
      product_id: "dream-job-agent",
      product_name: "Dream Job Agent",
      environment: "production",
      run_id: "dream-run",
      comparison_run_id: "dream-approved",
      comparison_label: "Last approved good run",
      observed_at: "2026-08-28T12:00:00Z",
      observation_id: "source-linkedin-coverage",
      case: {
        case_id: "dj-linkedin-pm-bengaluru-042",
        display_name: "LinkedIn PM search · Bengaluru · remote",
        use_case_id: "dream-job-search",
        segment: "product-manager / Bengaluru / remote",
        input_fingerprint: `sha256:${"b".repeat(64)}`,
      },
      component_id: "source-acquisition",
      stage_id: "retrieval",
      parameter_id: "linkedin-source-coverage",
      owner_id: "dream-job-source-owner",
      fix_location: "LinkedIn source adapter / connector-v2 mapping",
      layer: "RETRIEVAL_TOOL",
      concern: "INVARIANT",
      current_value: 0.42,
      expected_value: 0.91,
      current_summary: "LinkedIn returned 42% of the expected eligible jobs.",
      expected_summary: "The approved comparison returned 91% source coverage.",
      threshold: 0.85,
      unit: "ratio",
      regression_magnitude: 0.49,
      downstream_observation_ids: ["eligible-job-coverage", "resume-evidence-coverage"],
      reason_code: "UPSTREAM_SOURCE_COVERAGE_COLLAPSE",
      cause_category: "PROMPT_CONFIG_TOOL_CHANGE",
      cause_confidence: "SUPPORTED",
      evidence_level: "CONTROLLED_REPLAY",
      cause_reason: "Connector v1 passed this case while connector v2 failed with other versions fixed.",
      changes_since_comparison: [
        { dimension: "TOOLSET", previous: "connectors@1", current: "connectors@2" },
      ],
      maintenance: {
        eval_action: "KEEP",
        golden_dataset_action: "KEEP",
        reason: "Current evidence points to the product path, not the eval or approved case set.",
      },
      remediation: {
        action: "Open the LinkedIn source adapter before changing downstream evals.",
      },
      evidence_refs: [{
        uri: "artifact://demo/dream/source.json",
        sha256: `sha256:${"a".repeat(64)}`,
      }],
    },
  ],
  trend: [
    { product_id: "dream-job-agent", environment: "production", observed_at: "2026-08-27T12:00:00Z", health: "HEALTHY", pass_rate: 1 },
    { product_id: "dream-job-agent", environment: "production", observed_at: "2026-08-28T12:00:00Z", health: "FAILING", pass_rate: 0.6 },
    { product_id: "linkedin-research-os", environment: "production", observed_at: "2026-08-27T10:00:00Z", health: "HEALTHY", pass_rate: 1 },
    { product_id: "linkedin-research-os", environment: "production", observed_at: "2026-08-28T10:00:00Z", health: "HEALTHY", pass_rate: 1 },
  ],
};

function fetchOverview(overview: MonitoringOverview = OVERVIEW): typeof fetch {
  return async () => new Response(JSON.stringify(overview), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("MonitoringDashboard", () => {
  it("shows the exact case, earned cause, and fix location in plain language", async () => {
    render(<MonitoringDashboard fetcher={fetchOverview()} />);

    expect(await screen.findByRole("heading", { name: /see the exact failure/i })).toBeInTheDocument();
    expect(screen.getByText(/simulation, not production/i)).toBeInTheDocument();
    const diagnosis = screen.getByRole("heading", { name: /where to start/i }).closest("section");
    expect(diagnosis).not.toBeNull();
    expect(within(diagnosis!).getByText(/dj-linkedin-pm-bengaluru-042/i)).toBeInTheDocument();
    expect(within(diagnosis!).getByText("Current result")).toBeInTheDocument();
    expect(within(diagnosis!).getByText("Expected result")).toBeInTheDocument();
    expect(within(diagnosis!).getByText("Pass bar")).toBeInTheDocument();
    expect(within(diagnosis!).getByText("49 percentage points")).toBeInTheDocument();
    expect(within(diagnosis!).getByText("LinkedIn source adapter / connector-v2 mapping")).toBeInTheDocument();
    expect(within(diagnosis!).getByText("Supported cause")).toBeInTheDocument();
    expect(screen.getByText(/production guardrail not proven/i)).toBeInTheDocument();
    expect(screen.queryByText("Observed")).not.toBeInTheDocument();
    expect(screen.queryByText("Baseline")).not.toBeInTheDocument();
    expect(screen.queryByText("Propagation")).not.toBeInTheDocument();
  });

  it("shows missing comparison evidence without asserting an expected value", async () => {
    const unavailable: MonitoringOverview = {
      ...OVERVIEW,
      mode: "LIVE",
      incidents: [{
        ...OVERVIEW.incidents[0],
        comparison_label: "Comparison unavailable",
        expected_value: null,
        expected_summary: "The referenced comparison run is not stored, so this expectation is not verified.",
        regression_magnitude: null,
        changes_since_comparison: [],
      }],
    };

    render(<MonitoringDashboard fetcher={fetchOverview(unavailable)} />);

    expect(await screen.findByText("Difference unavailable")).toBeInTheDocument();
    expect(screen.getByText(/expectation is not verified/i)).toBeInTheDocument();
    expect(screen.getByText(/comparison unavailable: dream-approved/i)).toBeInTheDocument();
  });

  it("filters failed cases by product", async () => {
    render(<MonitoringDashboard fetcher={fetchOverview()} />);
    fireEvent.click(await screen.findByRole("button", { name: /linkedin research os/i }));
    expect(screen.getByText(/no starting failure found/i)).toBeInTheDocument();
  });

  it("keeps production incidents out of the staging product view", async () => {
    const stagingProduct = {
      ...OVERVIEW.products[0],
      environment: "staging",
      latest_run_id: "dream-staging-run",
      health: "HEALTHY" as const,
      fail_count: 0,
    };
    const multiEnvironmentOverview: MonitoringOverview = {
      ...OVERVIEW,
      products: [...OVERVIEW.products, stagingProduct],
      trend: [
        ...OVERVIEW.trend,
        {
          product_id: "dream-job-agent",
          environment: "staging",
          observed_at: "2026-08-28T12:05:00Z",
          health: "HEALTHY",
          pass_rate: 1,
        },
      ],
    };

    render(<MonitoringDashboard fetcher={fetchOverview(multiEnvironmentOverview)} />);
    fireEvent.click(await screen.findByRole("button", { name: /dream job agent staging/i }));
    expect(screen.getByText(/no starting failure found/i)).toBeInTheDocument();
  });

  it("keeps legal control characters from colliding product filters", async () => {
    const first = {
      ...OVERVIEW.products[0],
      product_id: "a",
      environment: "b\u001fc",
      display_name: "First product",
    };
    const second = {
      ...OVERVIEW.products[1],
      product_id: "a\u001fb",
      environment: "c",
      display_name: "Second product",
    };
    const collisionOverview: MonitoringOverview = {
      ...OVERVIEW,
      products: [first, second],
      incidents: [{
        ...OVERVIEW.incidents[0],
        product_id: first.product_id,
        product_name: first.display_name,
        environment: first.environment,
      }],
      trend: [
        { ...OVERVIEW.trend[0], product_id: first.product_id, environment: first.environment },
        { ...OVERVIEW.trend[2], product_id: second.product_id, environment: second.environment },
      ],
    };

    render(<MonitoringDashboard fetcher={fetchOverview(collisionOverview)} />);
    fireEvent.click(await screen.findByRole("button", { name: /second product/i }));

    expect(screen.getByText(/no starting failure found/i)).toBeInTheDocument();
    expect(screen.queryByText(/dj-linkedin-pm-bengaluru-042/i)).not.toBeInTheDocument();
  });

  it("does not describe blocked evidence as within approved bars", async () => {
    const blockedOverview: MonitoringOverview = {
      ...OVERVIEW,
      products: [{ ...OVERVIEW.products[0], health: "BLOCKED" }],
      incidents: [],
    };

    render(<MonitoringDashboard fetcher={fetchOverview(blockedOverview)} />);
    expect(await screen.findByText(/no confirmed starting point yet/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence is blocked, incomplete/i)).toBeInTheDocument();
    expect(screen.queryByText(/within their approved bars/i)).not.toBeInTheDocument();
  });

  it("refreshes the overview without reloading the page", async () => {
    const refreshed: MonitoringOverview = {
      ...OVERVIEW,
      generated_at: "2026-08-28T12:05:00Z",
      products: OVERVIEW.products.map((product) => ({
        ...product,
        health: "HEALTHY" as const,
        fail_count: 0,
      })),
      incidents: [],
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(OVERVIEW), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(refreshed), { status: 200 }));

    render(<MonitoringDashboard fetcher={fetcher} />);
    await screen.findByText("1/2");
    fireEvent.click(screen.getByRole("button", { name: /refresh data/i }));

    expect(await screen.findByText("2/2")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps stale data visible but warns when refresh fails", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(OVERVIEW), { status: 200 }))
      .mockRejectedValueOnce(new Error("offline"));

    render(<MonitoringDashboard fetcher={fetcher} />);
    await screen.findByText("1/2");
    fireEvent.click(screen.getByRole("button", { name: /refresh data/i }));

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent(/refresh failed.*may be stale/i);
    expect(warning).toHaveTextContent(/monitoring service is unreachable/i);
    expect(screen.getByText(/dj-linkedin-pm-bengaluru-042/i)).toBeInTheDocument();
  });

  it("resets a product filter that disappears after refresh", async () => {
    const refreshed: MonitoringOverview = {
      ...OVERVIEW,
      products: [OVERVIEW.products[0]],
      trend: OVERVIEW.trend.filter((point) => point.product_id === "dream-job-agent"),
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(OVERVIEW), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(refreshed), { status: 200 }));

    render(<MonitoringDashboard fetcher={fetcher} />);
    fireEvent.click(await screen.findByRole("button", { name: /linkedin research os/i }));
    expect(screen.queryByText(/dj-linkedin-pm-bengaluru-042/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /refresh data/i }));

    expect(await screen.findByText(/dj-linkedin-pm-bengaluru-042/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /all products/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
