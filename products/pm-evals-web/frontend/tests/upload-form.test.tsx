// Screen S-1's upload journey (J-2..J-5, J-9): the four contract states
// (empty/loading/error/success), client-side pre-validation feedback, API
// error surfacing, and hostile-string safety. The fetcher is injected so the
// REAL typed client runs in every test — only the network is fake.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
  it("flags a browser-unparseable baseline as advisory and lets the server decide", async () => {
    // The client parser is stricter than the server's (NaN tokens, encoding
    // differences) — so an unparseable file warns but never blocks; the
    // submission goes through and the SERVER's named 422 is what the user sees.
    const detail = [
      {
        source: "baseline",
        issues: [{ location: "baseline", message: "not valid JSON: server's own words" }],
      },
    ];
    render(<UploadForm fetcher={fetchReturning(422, { detail })} />);
    selectFile(/baseline/i, fileOf("{broken", "baseline.json"));
    expect(await screen.findByText(/not valid JSON in this browser's reading/)).toBeInTheDocument();
    selectFile(/candidate/i, fileOf(VALID_CANDIDATE, "candidate.json"));
    const button = screen.getByRole("button", { name: /compare runs/i });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("server's own words");
  });

  it("blocks an oversized file — a refusal the server is known to share", async () => {
    render(<UploadForm />);
    const oversized = new File([new ArrayBuffer(5 * 1024 * 1024 + 1)], "baseline.json", {
      type: "application/json",
    });
    selectFile(/baseline/i, oversized);
    expect(await screen.findByText(/5 MB/)).toBeInTheDocument();
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

  it("locks the file inputs while a comparison is in flight — no stale-response race", async () => {
    const never: typeof fetch = () => new Promise(() => {});
    render(<UploadForm fetcher={never} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    await screen.findByRole("status");
    expect(screen.getByLabelText(/baseline/i)).toBeDisabled();
    expect(screen.getByLabelText(/candidate/i)).toBeDisabled();
  });

  it("blocks submission while a re-selected file is still being read — the old pair can never be sent", async () => {
    // A re-select whose FileReader completion would land mid-flight was the
    // R2-1 race: submit inside the read window sends the OLD pair while the
    // note soon shows the new file. Gate the reader to hold that window open.
    const releases: Array<() => void> = [];
    const RealFileReader = FileReader;
    class GatedFileReader {
      result: string | ArrayBuffer | null = null;
      error: DOMException | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsText(file: File): void {
        const inner = new RealFileReader();
        inner.onload = () => {
          releases.push(() => {
            this.result = inner.result;
            this.onload?.();
          });
        };
        inner.readAsText(file);
      }
    }
    vi.stubGlobal("FileReader", GatedFileReader as unknown as typeof FileReader);
    try {
      render(<UploadForm />);
      selectFile(/baseline/i, fileOf(VALID_BASELINE, "baseline.json"));
      selectFile(/candidate/i, fileOf(VALID_CANDIDATE, "candidate.json"));
      await waitFor(() => expect(releases).toHaveLength(2));
      act(() => releases.splice(0).forEach((release) => release()));
      const button = screen.getByRole("button", { name: /compare runs/i });
      await waitFor(() => expect(button).toBeEnabled());
      // re-select the baseline; its read is now pending and NOT released
      selectFile(/baseline/i, fileOf(VALID_BASELINE, "new-baseline.json"));
      await waitFor(() => expect(releases).toHaveLength(1));
      expect(button).toBeDisabled(); // pending read blocks submit — no stale pair
      act(() => releases.splice(0).forEach((release) => release()));
      await waitFor(() => expect(button).toBeEnabled());
      expect(screen.getByText(/new-baseline\.json/)).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("discards a stale slow read: the last-SELECTED file wins, not the last-COMPLETED (F-1)", async () => {
    // Re-selecting the same source while its first read is still in flight is a
    // race: without a per-source generation token, the slower FIRST read
    // completing AFTER the faster SECOND read overwrites the newer file, and the
    // form then submits the stale pair while the input holds the newer file.
    const releases: Array<() => void> = [];
    const RealFileReader = FileReader;
    class GatedFileReader {
      result: string | ArrayBuffer | null = null;
      error: DOMException | null = null;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      readAsText(file: File): void {
        const inner = new RealFileReader();
        inner.onload = () => {
          releases.push(() => {
            this.result = inner.result;
            this.onload?.();
          });
        };
        inner.readAsText(file);
      }
    }
    vi.stubGlobal("FileReader", GatedFileReader as unknown as typeof FileReader);
    try {
      render(<UploadForm />);
      // First selection (its read will be released LAST — the stale one).
      selectFile(/baseline/i, fileOf(VALID_BASELINE, "stale-A.json"));
      await waitFor(() => expect(releases).toHaveLength(1));
      // Re-select the SAME source before the first read resolves.
      selectFile(/baseline/i, fileOf(VALID_BASELINE, "fresh-B.json"));
      await waitFor(() => expect(releases).toHaveLength(2));
      // The newer selection (B) completes first...
      act(() => releases[1]());
      // ...then the older selection (A) completes late; it must be discarded.
      act(() => releases[0]());
      // The form holds the last-SELECTED file, never the last-COMPLETED one.
      await waitFor(() => expect(screen.getByText(/fresh-B\.json/)).toBeInTheDocument());
      expect(screen.queryByText(/stale-A\.json/)).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("announces status changes politely to assistive technology", async () => {
    const never: typeof fetch = () => new Promise(() => {});
    render(<UploadForm fetcher={never} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
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

  it("clears a previous error on resubmit — no alert beside a success banner", async () => {
    let calls = 0;
    const failThenSucceed: typeof fetch = async () => {
      calls += 1;
      if (calls === 1) {
        return new Response(JSON.stringify({ detail: "too big" }), {
          status: 413,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ comparison: PROCEED_COMPARISON }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };
    render(<UploadForm fetcher={failThenSucceed} />);
    await selectBothValidFiles();
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: /compare runs/i }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("PROCEED");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
