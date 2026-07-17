// Screen S-1's upload journey (J-2..J-5, J-9): the four contract states
// (empty/loading/error/success), client-side pre-validation feedback, API
// error surfacing, and hostile-string safety. The fetcher is injected so the
// REAL typed client runs in every test — only the network is fake.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UploadForm } from "@/components/upload-form";

const VALID_BASELINE = JSON.stringify({
  format_version: 1,
  suite: "support-copilot-v2",
  criteria: [{ id: "C-1", name: "Accuracy" }],
  traces: [{ trace_id: "T-1", results: { "C-1": "fail" } }],
});

const VALID_CANDIDATE = JSON.stringify({
  format_version: 1,
  suite: "support-copilot-v2",
  criteria: [{ id: "C-1", name: "Accuracy" }],
  traces: [{ trace_id: "T-1", results: { "C-1": "pass" } }],
});

const PROCEED_COMPARISON = {
  verdict: "PROCEED",
  matched_traces: 1,
  reasons: [],
};

function fileOf(content: string, name = "run.json"): File {
  return new File([content], name, { type: "application/json" });
}

function fetchReturning(status: number, body: unknown): typeof fetch {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

function selectFile(labelPattern: RegExp, file: File): void {
  const input = screen.getByLabelText(labelPattern);
  fireEvent.change(input, { target: { files: [file] } });
}

async function selectBothValidFiles(): Promise<void> {
  selectFile(/baseline/i, fileOf(VALID_BASELINE, "baseline.json"));
  selectFile(/candidate/i, fileOf(VALID_CANDIDATE, "candidate.json"));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeEnabled(),
  );
}

describe("UploadForm — empty state (J-2/J-3)", () => {
  it("renders labeled file inputs and a disabled Compare button", () => {
    render(<UploadForm />);
    expect(screen.getByLabelText(/baseline/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/candidate/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeDisabled();
  });

  it("enables Compare Runs once both files pre-validate", async () => {
    render(<UploadForm />);
    await selectBothValidFiles();
  });
});

describe("UploadForm — client-side pre-validation (J-4)", () => {
  it("names a malformed baseline and keeps Compare disabled", async () => {
    render(<UploadForm />);
    selectFile(/baseline/i, fileOf("{broken", "baseline.json"));
    expect(await screen.findByText(/not valid JSON/)).toBeInTheDocument();
    selectFile(/candidate/i, fileOf(VALID_CANDIDATE, "candidate.json"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /compare runs/i })).toBeDisabled(),
    );
  });

  it("names an incompatible pair before any request is sent", async () => {
    render(<UploadForm />);
    selectFile(/baseline/i, fileOf(VALID_BASELINE, "baseline.json"));
    selectFile(
      /candidate/i,
      fileOf(VALID_CANDIDATE.replace("support-copilot-v2", "another-suite"), "candidate.json"),
    );
    expect(await screen.findByText(/suite mismatch/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeDisabled();
  });
});

describe("UploadForm — loading state (J-5)", () => {
  it("announces the in-flight comparison and disables the button", async () => {
    const never: typeof fetch = () => new Promise(() => {});
    render(<UploadForm fetcher={never} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toMatch(/comparing/i);
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeDisabled();
  });
});

describe("UploadForm — success state and reset (J-5, J-9)", () => {
  it("announces the verdict and resets to empty on Start a new comparison", async () => {
    render(<UploadForm fetcher={fetchReturning(200, { comparison: PROCEED_COMPARISON })} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("PROCEED");
    fireEvent.click(screen.getByRole("button", { name: /start a new comparison/i }));
    await waitFor(() => expect(screen.queryByText(/PROCEED/)).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /compare runs/i })).toBeDisabled();
  });
});

describe("UploadForm — API error surfacing (J-4)", () => {
  it("renders server-side named issues per source as an alert", async () => {
    const detail = [
      {
        source: "candidate",
        issues: [{ location: "candidate", message: "duplicate trace_id 'T-1'" }],
      },
    ];
    render(<UploadForm fetcher={fetchReturning(422, { detail })} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("candidate");
    expect(alert.textContent).toContain("duplicate trace_id 'T-1'");
  });

  it("renders the 413 size message as an alert", async () => {
    render(<UploadForm fetcher={fetchReturning(413, { detail: "too big" })} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("5 MB");
  });

  it("renders the unreachable message when the network fails", async () => {
    const failing: typeof fetch = async () => {
      throw new Error("ECONNREFUSED");
    };
    render(<UploadForm fetcher={failing} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/unreachable/i);
  });
});

describe("UploadForm — hostile strings render as text, never as markup", () => {
  it("escapes a hostile filename", async () => {
    render(<UploadForm />);
    const hostile = '<img src=x onerror="window.pwned=true">.json';
    selectFile(/baseline/i, fileOf(VALID_BASELINE, hostile));
    expect(await screen.findByText(new RegExp("onerror"))).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect((window as unknown as { pwned?: boolean }).pwned).toBeUndefined();
  });

  it("escapes hostile HTML inside server-sent issue messages", async () => {
    const detail = [
      {
        source: "baseline",
        issues: [{ location: "baseline", message: '<script>window.pwned=true</script>' }],
      },
    ];
    render(<UploadForm fetcher={fetchReturning(422, { detail })} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("<script>");
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { pwned?: boolean }).pwned).toBeUndefined();
  });
});
