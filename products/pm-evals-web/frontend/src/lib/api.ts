// The typed API client: every call and shape derives from the committed
// OpenAPI contract (api-types.gen.ts is generated from ../backend/openapi.json
// and CI fails when it drifts). The UI can never depend on an undocumented
// field: these are the only response types the app knows.
import type { components } from "@/lib/api-types.gen";

export type Comparison = components["schemas"]["Comparison"];
export type CompareResponse = components["schemas"]["CompareResponse"];
export type CriterionDelta = components["schemas"]["CriterionDelta"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type ParseIssue = components["schemas"]["ParseIssue"];
export type ValidationProblem = components["schemas"]["ValidationProblem"];
export type VerdictReason = components["schemas"]["VerdictReason"];

export type ApiResult<T> =
  | { kind: "ok"; value: T }
  | { kind: "validation"; problems: ValidationProblem[] }
  | { kind: "error"; message: string };

function comparePayload(baseline: File, candidate: File): FormData {
  const form = new FormData();
  form.append("baseline", baseline);
  form.append("candidate", candidate);
  return form;
}

function frameworkFallback(): ValidationProblem[] {
  // framework-shaped or unreadable 422 (missing part / bad form field / non-JSON
  // body) — anything that is not the J-4 named-issues shape
  return [
    {
      source: "baseline",
      issues: [{ location: "request", message: "The request was not accepted. Re-select both files and try again." }],
    },
  ];
}

async function readValidationProblems(response: Response): Promise<ValidationProblem[]> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return frameworkFallback();
  }
  const detail = (body as { detail?: unknown }).detail;
  if (
    Array.isArray(detail) &&
    detail.length > 0 &&
    detail.every((p) => typeof p === "object" && p !== null && "source" in p)
  ) {
    return detail as ValidationProblem[];
  }
  return frameworkFallback();
}

export async function compareRuns(
  baseline: File,
  candidate: File,
  fetcher: typeof fetch = fetch,
): Promise<ApiResult<Comparison>> {
  let response: Response;
  try {
    response = await fetcher("/api/compare", { method: "POST", body: comparePayload(baseline, candidate) });
  } catch {
    return { kind: "error", message: "The comparison service is unreachable. Is the app running?" };
  }
  if (response.status === 422) {
    return { kind: "validation", problems: await readValidationProblems(response) };
  }
  if (response.status === 413) {
    return { kind: "error", message: "One of the files is larger than the 5 MB limit." };
  }
  if (!response.ok) {
    return { kind: "error", message: `The comparison failed (HTTP ${response.status}).` };
  }
  let body: CompareResponse;
  try {
    body = (await response.json()) as CompareResponse;
  } catch {
    return { kind: "error", message: "The comparison service returned an unreadable response." };
  }
  return { kind: "ok", value: body.comparison };
}

export async function downloadReport(
  baseline: File,
  candidate: File,
  format: "markdown" | "json",
  fetcher: typeof fetch = fetch,
): Promise<ApiResult<Blob>> {
  const form = comparePayload(baseline, candidate);
  form.append("format", format);
  let response: Response;
  try {
    response = await fetcher("/api/report", { method: "POST", body: form });
  } catch {
    return { kind: "error", message: "The report service is unreachable." };
  }
  if (response.status === 422) {
    return { kind: "validation", problems: await readValidationProblems(response) };
  }
  if (response.status === 413) {
    return { kind: "error", message: "One of the files is larger than the 5 MB limit." };
  }
  if (!response.ok) {
    return { kind: "error", message: `The report download failed (HTTP ${response.status}).` };
  }
  let blob: Blob;
  try {
    blob = await response.blob();
  } catch {
    // a body-stream failure after a 200 must stay a recoverable result —
    // an exception here would strand the caller's in-flight state
    return { kind: "error", message: "The report download failed mid-transfer. Try again." };
  }
  return { kind: "ok", value: blob };
}

export async function health(fetcher: typeof fetch = fetch): Promise<ApiResult<HealthResponse>> {
  try {
    const response = await fetcher("/api/health");
    if (!response.ok) {
      return { kind: "error", message: `HTTP ${response.status}` };
    }
    return { kind: "ok", value: (await response.json()) as HealthResponse };
  } catch {
    return { kind: "error", message: "unreachable" };
  }
}
