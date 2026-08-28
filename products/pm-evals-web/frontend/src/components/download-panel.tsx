"use client";

// Journey J-8: download the comparison as Markdown or JSON. The report is
// regenerated server-side from the same two files (nothing is stored,
// PD-V3-08) through the typed client; filenames mirror the server's constant
// Content-Disposition names. One download runs at a time; failures surface
// as a recoverable alert and the next attempt clears it.

import { useState } from "react";

import { downloadReport, type ValidationProblem } from "@/lib/api";

type Format = "markdown" | "json";

// mirror of the server-generated Content-Disposition filenames (app.py)
const FILENAMES: Record<Format, string> = {
  markdown: "eval-comparison.md",
  json: "eval-comparison.json",
};

interface DownloadPanelProps {
  baseline: File;
  candidate: File;
  // Injected in tests so the real typed client runs against a fake network.
  fetcher?: typeof fetch;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    // cleanup must not depend on click() succeeding
    anchor.remove();
    URL.revokeObjectURL(url);
  }
}

export function DownloadPanel({ baseline, candidate, fetcher = fetch }: DownloadPanelProps) {
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<ValidationProblem[] | null>(null);

  async function handleDownload(format: Format): Promise<void> {
    setBusy(format);
    setError(null);
    setProblems(null);
    const result = await downloadReport(baseline, candidate, format, fetcher);
    setBusy(null);
    if (result.kind === "ok") {
      saveBlob(result.value, FILENAMES[format]);
      return;
    }
    if (result.kind === "validation") {
      setProblems(result.problems);
    } else {
      setError(result.message);
    }
  }

  return (
    <section aria-labelledby="download-heading" className="download-panel">
      <h2 id="download-heading">Download the report</h2>
      <p>
        The report is regenerated from your two files on demand — nothing was
        stored on the server.
      </p>
      <div className="download-buttons">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void handleDownload("markdown")}
        >
          Download Markdown report
        </button>
        <button type="button" disabled={busy !== null} onClick={() => void handleDownload("json")}>
          Download JSON report
        </button>
      </div>
      {busy !== null && (
        <p role="status" aria-live="polite">
          Preparing the {busy === "markdown" ? "Markdown" : "JSON"} report…
        </p>
      )}
      {(error !== null || problems !== null) && (
        <div role="alert" className="api-errors">
          {error !== null && <p>{error}</p>}
          {problems !== null && (
            <ul className="issues">
              {problems.map((problem) =>
                problem.issues.map((issue) => (
                  <li key={problem.source + issue.location + issue.message}>
                    <strong>{problem.source}</strong>: {issue.message}
                  </li>
                )),
              )}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
