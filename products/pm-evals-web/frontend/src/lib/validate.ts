// Client-side pre-validation of eval-run files (journey step J-4): fast,
// named feedback before anything is uploaded. The backend's parser
// (pm_evals_compare.parse_run) and its compatibility check remain
// authoritative; this mirror exists so a non-technical PM sees problems
// immediately. Two result channels keep the mirror honest:
//
// - `issues` (blocking): checks whose refusal the server is KNOWN to share —
//   the 5 MB cap, top-level object, format_version, suite/criteria/traces
//   presence, and (once both files parse) suite mismatch and shared-id
//   checks. These messages mirror the backend's character for character
//   where the backend has a fixed string (the compatibility trio, the size
//   cap, "the file must be a JSON object", the format_version message
//   shape); presence checks use client wording since the server's come from
//   pydantic, and the parse-failure advisory is deliberately client-worded.
// - `advisories` (non-blocking): the client could not tell. JSON.parse is
//   STRICTER than Python's json.loads (NaN/Infinity tokens, some encodings
//   FileReader decodes differently), so a browser-side parse failure must
//   not refuse a file the server might accept — the form stays submittable
//   and the server decides.
//
// Anything deeper (duplicate ids, undeclared criteria, field-level typing)
// is left to the server on purpose: the mirror fails open, never refusing a
// file the backend would accept.

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // mirrors backend MAX_UPLOAD_BYTES
export const FORMAT_VERSION = 1; // mirrors backend FORMAT_VERSION

export type UploadSource = "baseline" | "candidate";

export interface LocalIssue {
  location: string;
  message: string;
}

export interface PreParsedRun {
  suite: string;
  criterionIds: string[];
  traceIds: string[];
  // false when some entries carried no string id — the arrays above are then
  // incomplete and shared-id pair checks must not run (the server will name
  // the precise field problem instead).
  criterionIdsComplete: boolean;
  traceIdsComplete: boolean;
}

export interface PreValidation {
  issues: LocalIssue[]; // blocking: the server is known to refuse these too
  advisories: LocalIssue[]; // non-blocking: unknown to the client, server decides
  run: PreParsedRun | null;
}

function idsOf(entries: unknown[], key: string): { ids: string[]; complete: boolean } {
  const ids: string[] = [];
  let complete = true;
  for (const entry of entries) {
    const value =
      typeof entry === "object" && entry !== null
        ? (entry as Record<string, unknown>)[key]
        : null;
    if (typeof value === "string") {
      ids.push(value);
    } else {
      complete = false;
    }
  }
  return { ids, complete };
}

// The cap in whole MB, floored like the backend's message
// (MAX_UPLOAD_BYTES // (1024 * 1024)), so the displayed limit is derived from
// the constant and can never drift from it into a stale hardcoded number.
export const MAX_UPLOAD_MB = Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024));

export function preValidateFile(source: UploadSource, size: number, text: string): PreValidation {
  if (size > MAX_UPLOAD_BYTES) {
    return {
      issues: [{ location: source, message: `${source} file exceeds the ${MAX_UPLOAD_MB} MB limit` }],
      advisories: [],
      run: null,
    };
  }
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (exc) {
    // JSON.parse is stricter than the server's parser (Python json.loads
    // accepts NaN/Infinity tokens; FileReader may mis-decode encodings the
    // server detects) — so this cannot block. The server decides.
    return {
      issues: [],
      advisories: [
        {
          location: source,
          message:
            `not valid JSON in this browser's reading: ${String(exc)} — ` +
            "you can still run the comparison; the server makes the final call",
        },
      ],
      run: null,
    };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return {
      issues: [{ location: source, message: "the file must be a JSON object" }],
      advisories: [],
      run: null,
    };
  }
  const run = data as Record<string, unknown>;
  if (run.format_version !== FORMAT_VERSION) {
    return {
      issues: [
        {
          location: `${source}.format_version`,
          message:
            `unsupported format_version ${JSON.stringify(run.format_version)} ` +
            `(supported: ${FORMAT_VERSION})`,
        },
      ],
      advisories: [],
      run: null,
    };
  }
  const issues: LocalIssue[] = [];
  if (typeof run.suite !== "string" || run.suite.length === 0) {
    issues.push({ location: `${source}.suite`, message: "a non-empty suite name is required" });
  }
  if (!Array.isArray(run.criteria)) {
    issues.push({ location: `${source}.criteria`, message: "criteria must be a list" });
  }
  if (!Array.isArray(run.traces)) {
    issues.push({ location: `${source}.traces`, message: "traces must be a list" });
  }
  if (issues.length > 0) {
    return { issues, advisories: [], run: null };
  }
  const criteria = idsOf(run.criteria as unknown[], "id");
  const traces = idsOf(run.traces as unknown[], "trace_id");
  return {
    issues: [],
    advisories: [],
    run: {
      suite: run.suite as string,
      criterionIds: criteria.ids,
      traceIds: traces.ids,
      criterionIdsComplete: criteria.complete,
      traceIdsComplete: traces.complete,
    },
  };
}

// Mirrors pm_evals_compare.check_compatibility, message for message. The
// shared-id checks only run when both sides extracted a complete id set —
// on lossy extraction the server's field-level 422 names the real problem.
export function preValidatePair(baseline: PreParsedRun, candidate: PreParsedRun): LocalIssue[] {
  const issues: LocalIssue[] = [];
  if (baseline.suite !== candidate.suite) {
    issues.push({
      location: "pair",
      message: `suite mismatch: baseline is '${baseline.suite}', candidate is '${candidate.suite}'`,
    });
  }
  if (baseline.criterionIdsComplete && candidate.criterionIdsComplete) {
    const sharedCriteria = baseline.criterionIds.filter((id) =>
      candidate.criterionIds.includes(id),
    );
    if (sharedCriteria.length === 0) {
      issues.push({
        location: "pair",
        message: "the runs share no criteria — nothing is comparable",
      });
    }
  }
  if (baseline.traceIdsComplete && candidate.traceIdsComplete) {
    const sharedTraces = baseline.traceIds.filter((id) => candidate.traceIds.includes(id));
    if (sharedTraces.length === 0) {
      issues.push({
        location: "pair",
        message: "the runs share no trace ids — nothing is comparable",
      });
    }
  }
  return issues;
}
