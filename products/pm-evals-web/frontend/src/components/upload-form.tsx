"use client";

// Screen S-1's upload journey (J-2..J-5, J-9). The contract's four states for
// this screen — empty, loading, error, success — are explicit here: `phase`
// carries empty/loading/success, and errors render whenever local issues or an
// API failure exist. Client-side pre-validation (src/lib/validate.ts) is
// advisory; the server re-checks everything on compare. Rendering uses plain
// JSX text nodes throughout — filenames and server-sent messages are escaped
// by React, never injected as markup.

import { useId, useState } from "react";

import { compareRuns, type Comparison, type ValidationProblem } from "@/lib/api";
import {
  MAX_UPLOAD_BYTES,
  preValidateFile,
  preValidatePair,
  type LocalIssue,
  type PreValidation,
  type UploadSource,
} from "@/lib/validate";

type Phase = "empty" | "loading" | "success";

interface SelectedFile {
  file: File;
  pre: PreValidation;
}

interface UploadFormProps {
  // Injected in tests so the real typed client runs against a fake network.
  fetcher?: typeof fetch;
}

// FileReader instead of File.text(): supported everywhere the app runs,
// including the jsdom test environment (whose File has no .text()).
function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error("unreadable file"));
    reader.readAsText(file);
  });
}

function issueList(issues: LocalIssue[], className = "issues"): React.ReactElement {
  return (
    <ul className={className}>
      {issues.map((issue) => (
        <li key={issue.location + issue.message}>{issue.message}</li>
      ))}
    </ul>
  );
}

export function UploadForm({ fetcher = fetch }: UploadFormProps) {
  const baselineInputId = useId();
  const candidateInputId = useId();
  const [phase, setPhase] = useState<Phase>("empty");
  const [selected, setSelected] = useState<Partial<Record<UploadSource, SelectedFile>>>({});
  const [apiProblems, setApiProblems] = useState<ValidationProblem[] | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [formKey, setFormKey] = useState(0); // bumped on reset to clear the file inputs
  // File reads are async: a submit inside a pending read's window would send
  // the OLD pair while the note soon shows the new file. Submission is
  // blocked until every started read has applied its result; combined with
  // the in-flight input lock, no handleSelect completion can ever land while
  // a comparison is loading.
  const [pendingReads, setPendingReads] = useState(0);

  const pairIssues: LocalIssue[] =
    selected.baseline?.pre.run && selected.candidate?.pre.run
      ? preValidatePair(selected.baseline.pre.run, selected.candidate.pre.run)
      : [];
  const localIssues: Record<UploadSource, LocalIssue[]> = {
    baseline: selected.baseline?.pre.issues ?? [],
    candidate: selected.candidate?.pre.issues ?? [],
  };
  const advisories: Record<UploadSource, LocalIssue[]> = {
    baseline: selected.baseline?.pre.advisories ?? [],
    candidate: selected.candidate?.pre.advisories ?? [],
  };
  // Blocking issues block; advisories do not — a file the browser cannot
  // parse may still be one the server accepts, so the server decides.
  const canSubmit =
    phase !== "loading" &&
    pendingReads === 0 &&
    selected.baseline != null &&
    selected.baseline.pre.issues.length === 0 &&
    selected.candidate != null &&
    selected.candidate.pre.issues.length === 0 &&
    pairIssues.length === 0;

  async function handleSelect(source: UploadSource, file: File | null): Promise<void> {
    setApiProblems(null);
    setApiError(null);
    setComparison(null);
    if (file === null) {
      setSelected((prev) => ({ ...prev, [source]: undefined }));
      return;
    }
    // Oversized files are refused on size alone — never read into memory.
    let pre: PreValidation;
    setPendingReads((n) => n + 1);
    try {
      const text = file.size <= MAX_UPLOAD_BYTES ? await readFileText(file) : "";
      pre = preValidateFile(source, file.size, text);
    } catch {
      // A local read failure is a client limitation, not proof the server
      // would refuse the file — advisory, never blocking.
      pre = {
        issues: [],
        advisories: [
          {
            location: source,
            message:
              "the file could not be read in this browser — " +
              "you can still run the comparison; the server makes the final call",
          },
        ],
        run: null,
      };
    }
    setSelected((prev) => ({ ...prev, [source]: { file, pre } }));
    setPhase("empty");
    setPendingReads((n) => n - 1);
  }

  async function handleSubmit(event: React.FormEvent): Promise<void> {
    event.preventDefault();
    if (!canSubmit || !selected.baseline || !selected.candidate) return;
    setPhase("loading");
    setApiProblems(null);
    setApiError(null);
    setComparison(null);
    const result = await compareRuns(selected.baseline.file, selected.candidate.file, fetcher);
    if (result.kind === "ok") {
      setComparison(result.value);
      setPhase("success");
      return;
    }
    if (result.kind === "validation") {
      setApiProblems(result.problems);
    } else {
      setApiError(result.message);
    }
    setPhase("empty");
  }

  function reset(): void {
    setSelected({});
    setApiProblems(null);
    setApiError(null);
    setComparison(null);
    setPhase("empty");
    setFormKey((k) => k + 1);
  }

  const hasErrors =
    localIssues.baseline.length > 0 ||
    localIssues.candidate.length > 0 ||
    pairIssues.length > 0 ||
    apiProblems !== null ||
    apiError !== null;

  return (
    <section aria-labelledby="upload-heading">
      <h2 id="upload-heading">Compare two runs</h2>
      <form key={formKey} onSubmit={handleSubmit} aria-busy={phase === "loading"}>
        <div className="file-field">
          <label htmlFor={baselineInputId}>Baseline eval results (JSON)</label>
          <input
            id={baselineInputId}
            type="file"
            accept="application/json,.json"
            disabled={phase === "loading"}
            onChange={(e) => void handleSelect("baseline", e.target.files?.[0] ?? null)}
          />
          {selected.baseline && (
            <p className="file-note">
              {selected.baseline.file.name}
              {selected.baseline.pre.run ? " — looks like a valid eval run" : ""}
            </p>
          )}
          {localIssues.baseline.length > 0 && issueList(localIssues.baseline)}
          {advisories.baseline.length > 0 && issueList(advisories.baseline, "advisories")}
        </div>
        <div className="file-field">
          <label htmlFor={candidateInputId}>Candidate eval results (JSON)</label>
          <input
            id={candidateInputId}
            type="file"
            accept="application/json,.json"
            disabled={phase === "loading"}
            onChange={(e) => void handleSelect("candidate", e.target.files?.[0] ?? null)}
          />
          {selected.candidate && (
            <p className="file-note">
              {selected.candidate.file.name}
              {selected.candidate.pre.run ? " — looks like a valid eval run" : ""}
            </p>
          )}
          {localIssues.candidate.length > 0 && issueList(localIssues.candidate)}
          {advisories.candidate.length > 0 && issueList(advisories.candidate, "advisories")}
        </div>
        {pairIssues.length > 0 && (
          <div className="pair-issues">
            <p>These two files cannot be compared:</p>
            {issueList(pairIssues)}
          </div>
        )}
        <button type="submit" disabled={!canSubmit}>
          Compare Runs
        </button>
      </form>

      {hasErrors && (apiProblems !== null || apiError !== null) && (
        <div role="alert" className="api-errors">
          {apiError !== null && <p>{apiError}</p>}
          {apiProblems !== null && (
            <ul className="issues">
              {apiProblems.map((problem) =>
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

      {(phase === "loading" || phase === "success") && (
        <div role="status" aria-live="polite" className="compare-status">
          {phase === "loading" && <p>Comparing runs…</p>}
          {phase === "success" && comparison !== null && (
            <>
              <p className={`verdict verdict-${comparison.verdict.toLowerCase()}`}>
                Comparison complete. Verdict: <strong>{comparison.verdict}</strong>
                {" — "}
                {comparison.matched_traces} matched trace
                {comparison.matched_traces === 1 ? "" : "s"}.
              </p>
              {/* The full evidence dashboard (S-2, J-6) renders here in PR 8. */}
              <button type="button" onClick={reset}>
                Start a new comparison
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
