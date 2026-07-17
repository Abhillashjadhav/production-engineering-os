// Journey J-8: download the comparison as Markdown and as JSON, with honest
// loading, error, and recovery states. The REAL typed client runs — only the
// network and the browser download sink (object URLs, anchor clicks) are fake.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadPanel } from "@/components/download-panel";

function fileOf(content: string, name: string): File {
  return new File([content], name, { type: "application/json" });
}

const BASELINE = fileOf("{}", "baseline.json");
const CANDIDATE = fileOf("{}", "candidate.json");

const clicked: Array<{ download: string; href: string }> = [];
const created: Blob[] = [];
let revoked = 0;

beforeEach(() => {
  clicked.length = 0;
  created.length = 0;
  revoked = 0;
  (URL as unknown as Record<string, unknown>).createObjectURL = vi.fn((blob: Blob) => {
    created.push(blob);
    return `blob:mock-${created.length}`;
  });
  (URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn(() => {
    revoked += 1;
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push({ download: this.download, href: this.href });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  delete (URL as unknown as Record<string, unknown>).createObjectURL;
  delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
});

function markdownFetcher(): typeof fetch {
  return async () =>
    new Response("# Eval comparison\n\n## Verdict: HOLD\n", {
      status: 200,
      headers: { "content-type": "text/markdown; charset=utf-8" },
    });
}

describe("DownloadPanel — J-8 downloads", () => {
  it("downloads the Markdown report under the server's filename", async () => {
    render(<DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={markdownFetcher()} />);
    fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0].download).toBe("eval-comparison.md");
    expect(await created[0].text()).toContain("## Verdict: HOLD");
    expect(revoked).toBe(1); // no leaked object URLs
  });

  it("downloads the JSON report under the server's filename", async () => {
    const json: typeof fetch = async () =>
      new Response('{"comparison": {"verdict": "PROCEED"}}', {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    render(<DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={json} />);
    fireEvent.click(screen.getByRole("button", { name: /json/i }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0].download).toBe("eval-comparison.json");
  });

  it("announces the in-flight download and disables both buttons", async () => {
    const never: typeof fetch = () => new Promise(() => {});
    render(<DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={never} />);
    fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
    const status = await screen.findByRole("status");
    expect(status.textContent).toMatch(/preparing/i);
    expect(screen.getByRole("button", { name: /markdown/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /json/i })).toBeDisabled();
  });

  it("surfaces a failed download as an alert and recovers on retry", async () => {
    let calls = 0;
    const failThenSucceed: typeof fetch = async () => {
      calls += 1;
      if (calls === 1) return new Response("boom", { status: 500 });
      return new Response("# ok\n", {
        status: 200,
        headers: { "content-type": "text/markdown; charset=utf-8" },
      });
    };
    render(
      <DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={failThenSucceed} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/HTTP 500/);
    fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // recovered
  });

  it("renders named validation issues if the report endpoint refuses the pair", async () => {
    const detail = [
      { source: "baseline", issues: [{ location: "baseline", message: "not valid JSON: x" }] },
    ];
    const rejecting: typeof fetch = async () =>
      new Response(JSON.stringify({ detail }), {
        status: 422,
        headers: { "content-type": "application/json" },
      });
    render(<DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={rejecting} />);
    fireEvent.click(screen.getByRole("button", { name: /markdown/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("baseline");
    expect(alert.textContent).toContain("not valid JSON: x");
  });

  it("maps a network failure to the unreachable message", async () => {
    const failing: typeof fetch = async () => {
      throw new Error("ECONNREFUSED");
    };
    render(<DownloadPanel baseline={BASELINE} candidate={CANDIDATE} fetcher={failing} />);
    fireEvent.click(screen.getByRole("button", { name: /json/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/unreachable/i);
  });
});
