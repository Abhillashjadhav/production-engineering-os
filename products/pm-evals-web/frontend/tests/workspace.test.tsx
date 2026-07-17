// The S-1 → S-2/S-3 wiring: a successful comparison renders the dashboard
// and trace explorer beneath the upload form; reset and re-selection clear
// them. The REAL UploadForm, client, Dashboard, and TraceExplorer run —
// only the network is fake.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

// jsdom's File has no .text() — read the way the app itself does
function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
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

  it("offers the report downloads after a successful comparison (J-8)", async () => {
    render(<Workspace fetcher={fetchReturning(200, { comparison: regression })} />);
    await compareSuccessfully();
    expect(screen.getByRole("button", { name: /markdown/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /json/i })).toBeInTheDocument();
  });

  it("removes the download buttons when the comparison is cleared", async () => {
    render(<Workspace fetcher={fetchReturning(200, { comparison: regression })} />);
    await compareSuccessfully();
    fireEvent.click(screen.getByRole("button", { name: /start a new comparison/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /markdown/i })).not.toBeInTheDocument(),
    );
  });

  it("regenerates the report from the exact files that were compared", async () => {
    // The PR's integrity guarantee: the downloaded report can never describe
    // different files than the dashboard shows. A swapped or substituted
    // handoff pair must fail here, at the request boundary.
    const bodies: FormData[] = [];
    const fetcher: typeof fetch = async (_input, init) => {
      bodies.push(init?.body as FormData);
      if (bodies.length === 1) {
        return new Response(JSON.stringify({ comparison: regression }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("# report\n", {
        status: 200,
        headers: { "content-type": "text/markdown; charset=utf-8" },
      });
    };
    (URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(() => "blob:mock");
    (URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      render(<Workspace fetcher={fetcher} />);
      await compareSuccessfully();
      fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
      await waitFor(() => expect(bodies).toHaveLength(2));
      const baseline = bodies[1].get("baseline") as File;
      const candidate = bodies[1].get("candidate") as File;
      expect(baseline.name).toBe("baseline.json");
      expect(candidate.name).toBe("candidate.json");
      expect(await readText(baseline)).toBe(VALID_BASELINE);
      expect(await readText(candidate)).toBe(VALID_CANDIDATE);
    } finally {
      vi.restoreAllMocks();
      delete (URL as unknown as Record<string, unknown>).createObjectURL;
      delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
    }
  });
});
