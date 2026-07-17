// The S-1 → S-2/S-3 wiring: a successful comparison renders the dashboard
// and trace explorer beneath the upload form; reset and re-selection clear
// them. The REAL UploadForm, client, Dashboard, and TraceExplorer run —
// only the network is fake.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Workspace } from "@/components/workspace";
import type { Comparison } from "@/lib/api";

import regressionJson from "./fixtures/comparison_regression.json";

const regression = regressionJson as unknown as Comparison;

const VALID_BASELINE = JSON.stringify({
  format_version: 1,
  suite: "support-copilot-v2",
  criteria: [{ id: "C-1", name: "Accuracy" }],
  traces: [{ trace_id: "T-1", results: { "C-1": "fail" } }],
});

const VALID_CANDIDATE = VALID_BASELINE.replace('"fail"', '"pass"');

function fileOf(content: string, name: string): File {
  return new File([content], name, { type: "application/json" });
}

function fetchReturning(status: number, body: unknown): typeof fetch {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

async function compareSuccessfully(): Promise<void> {
  fireEvent.change(screen.getByLabelText(/baseline/i), {
    target: { files: [fileOf(VALID_BASELINE, "baseline.json")] },
  });
  fireEvent.change(screen.getByLabelText(/candidate/i), {
    target: { files: [fileOf(VALID_CANDIDATE, "candidate.json")] },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
  await screen.findByRole("region", { name: /release verdict/i });
}

describe("Workspace — S-1 feeds S-2/S-3", () => {
  it("renders the dashboard and trace explorer after a successful comparison", async () => {
    render(<Workspace fetcher={fetchReturning(200, { comparison: regression })} />);
    await compareSuccessfully();
    const panel = screen.getByRole("region", { name: /release verdict/i });
    expect(within(panel).getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /changed traces/i })).toBeInTheDocument();
  });

  it("clears the dashboard on Start a new comparison (J-9)", async () => {
    render(<Workspace fetcher={fetchReturning(200, { comparison: regression })} />);
    await compareSuccessfully();
    fireEvent.click(screen.getByRole("button", { name: /start a new comparison/i }));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: /release verdict/i })).not.toBeInTheDocument(),
    );
  });

  it("clears a stale dashboard when a new file is selected", async () => {
    render(<Workspace fetcher={fetchReturning(200, { comparison: regression })} />);
    await compareSuccessfully();
    fireEvent.change(screen.getByLabelText(/baseline/i), {
      target: { files: [fileOf(VALID_BASELINE, "another.json")] },
    });
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: /release verdict/i })).not.toBeInTheDocument(),
    );
  });
});
