// Client-side pre-validation of eval-run files (journey step J-4): fast,
// named feedback before anything is uploaded. ADVISORY ONLY — the backend's
// parser (pm_evals_compare.parse_run) and its compatibility check remain
// authoritative; this mirror exists so a non-technical PM sees problems
// immediately, in the same language the backend would use. Mirrored rules:
// the 5 MB cap, JSON parse, top-level object, format_version, suite/criteria/
// traces presence, suite mismatch, shared criteria, shared trace ids.
// Anything deeper (duplicate ids, undeclared criteria, field-level typing)
// is left to the server on purpose: a partial mirror must fail open, never
// refuse a file the backend would accept.

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
}

export interface PreValidation {
  issues: LocalIssue[];
  run: PreParsedRun | null;
}

function idsOf(entries: unknown[], key: string): string[] {
  return entries
    .map((e) => (typeof e === "object" && e !== null ? (e as Record<string, unknown>)[key] : null))
    .filter((v): v is string => typeof v === "string");
}

export function preValidateFile(source: UploadSource, size: number, text: string): PreValidation {
  if (size > MAX_UPLOAD_BYTES) {
    return {
      issues: [{ location: source, message: `${source} file exceeds the 5 MB limit` }],
      run: null,
    };
  }
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (exc) {
    return {
      issues: [{ location: source, message: `not valid JSON: ${String(exc)}` }],
      run: null,
    };
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return {
      issues: [{ location: source, message: "the file must be a JSON object" }],
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
    return { issues, run: null };
  }
  return {
    issues: [],
    run: {
      suite: run.suite as string,
      criterionIds: idsOf(run.criteria as unknown[], "id"),
      traceIds: idsOf(run.traces as unknown[], "trace_id"),
    },
  };
}

// Mirrors pm_evals_compare.check_compatibility, message for message.
export function preValidatePair(baseline: PreParsedRun, candidate: PreParsedRun): LocalIssue[] {
  const issues: LocalIssue[] = [];
  if (baseline.suite !== candidate.suite) {
    issues.push({
      location: "pair",
      message: `suite mismatch: baseline is '${baseline.suite}', candidate is '${candidate.suite}'`,
    });
  }
  const sharedCriteria = baseline.criterionIds.filter((id) => candidate.criterionIds.includes(id));
  if (sharedCriteria.length === 0) {
    issues.push({ location: "pair", message: "the runs share no criteria — nothing is comparable" });
  }
  const sharedTraces = baseline.traceIds.filter((id) => candidate.traceIds.includes(id));
  if (sharedTraces.length === 0) {
    issues.push({ location: "pair", message: "the runs share no trace ids — nothing is comparable" });
  }
  return issues;
}
