// The typed client's error-shape handling (J-4) and result discrimination.
import { describe, expect, it } from "vitest";

import { compareRuns, downloadReport, health } from "@/lib/api";
import { MAX_UPLOAD_BYTES } from "@/lib/validate";

// The size-limit the client reports on a 413 must be DERIVED from the upload
// cap, not a hardcoded number that could survive a cap change and mislead the
// user. mirror-parity.test.ts keeps MAX_UPLOAD_BYTES equal to the backend cap,
// so deriving from it here transitively pins the message to the server's cap.
const EXPECTED_MB = Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024));

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

describe("compareRuns", () => {
  it("returns the comparison on 200", async () => {
    const comparison = { verdict: "PROCEED", reasons: [] };
    const result = await compareRuns(
      fileOf("{}"),
      fileOf("{}"),
      fetchReturning(200, { comparison }),
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.value.verdict).toBe("PROCEED");
  });

  it("surfaces named per-source issues on the J-4 422 shape", async () => {
    const detail = [
      {
        source: "candidate",
        issues: [{ location: "candidate", message: "not valid JSON: ..." }],
      },
    ];
    const result = await compareRuns(fileOf("{}"), fileOf("x"), fetchReturning(422, { detail }));
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems[0].source).toBe("candidate");
      expect(result.problems[0].issues[0].message).toContain("not valid JSON");
    }
  });

  it("maps framework-shaped 422s to a recoverable message, never a crash", async () => {
    const detail = [{ loc: ["body", "baseline"], msg: "Field required", type: "missing" }];
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), fetchReturning(422, { detail }));
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems[0].issues[0].message).toContain("Re-select both files");
    }
  });

  it("maps 413 to a size-limit message derived from the upload cap", async () => {
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), fetchReturning(413, { detail: "too big" }));
    expect(result.kind).toBe("error");
    // the displayed limit is computed from MAX_UPLOAD_BYTES, never a stale literal
    if (result.kind === "error") expect(result.message).toContain(`${EXPECTED_MB} MB limit`);
  });

  it("maps network failure to an unreachable error", async () => {
    const failing: typeof fetch = async () => {
      throw new Error("ECONNREFUSED");
    };
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), failing);
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("unreachable");
  });

  it("treats an empty 422 detail list as the framework shape, not a silent pass", async () => {
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), fetchReturning(422, { detail: [] }));
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems).toHaveLength(1);
      expect(result.problems[0].issues[0].message).toContain("Re-select both files");
    }
  });

  it("surfaces a real request-field source from the unified 422 envelope (P-4)", async () => {
    // the backend now names transport-field errors by their real source, not a
    // mis-attributed "baseline"
    const detail = [
      { source: "min_matched_traces", issues: [{ location: "min_matched_traces", message: "must be >= 1" }] },
    ];
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), fetchReturning(422, { detail }));
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems[0].source).toBe("min_matched_traces");
    }
  });

  it("falls back safely when a 422 problem has a source but no issues array", async () => {
    // a malformed problem must never reach the renderer's problem.issues.map
    const result = await compareRuns(
      fileOf("{}"),
      fileOf("{}"),
      fetchReturning(422, { detail: [{ source: "candidate" }] }),
    );
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(Array.isArray(result.problems[0].issues)).toBe(true);
    }
  });

  it("maps a non-JSON 422 body to the recoverable framework message, never a crash", async () => {
    const htmlError: typeof fetch = async () =>
      new Response("<html>Bad Gateway</html>", {
        status: 422,
        headers: { "content-type": "text/html" },
      });
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), htmlError);
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems[0].issues[0].message).toContain("Re-select both files");
    }
  });

  it("maps a non-JSON 200 body to a recoverable error, never a crash", async () => {
    const htmlOk: typeof fetch = async () =>
      new Response("<html>proxy page</html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      });
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), htmlOk);
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("unreadable");
  });
});

describe("downloadReport", () => {
  it("returns the report body as a blob on 200", async () => {
    const markdown: typeof fetch = async () =>
      new Response("# Eval comparison\n\n## Verdict: PROCEED\n", {
        status: 200,
        headers: { "content-type": "text/markdown; charset=utf-8" },
      });
    const result = await downloadReport(fileOf("{}"), fileOf("{}"), "markdown", markdown);
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(await result.value.text()).toContain("## Verdict: PROCEED");
    }
  });

  it("maps 413 to a size-limit message derived from the upload cap", async () => {
    const result = await downloadReport(
      fileOf("{}"),
      fileOf("{}"),
      "json",
      fetchReturning(413, { detail: "too big" }),
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain(`${EXPECTED_MB} MB limit`);
  });

  it("surfaces named per-source issues on the J-4 422 shape", async () => {
    const detail = [
      {
        source: "baseline",
        issues: [{ location: "baseline", message: "not valid JSON: ..." }],
      },
    ];
    const result = await downloadReport(
      fileOf("x"),
      fileOf("{}"),
      "markdown",
      fetchReturning(422, { detail }),
    );
    expect(result.kind).toBe("validation");
    if (result.kind === "validation") {
      expect(result.problems[0].source).toBe("baseline");
      expect(result.problems[0].issues[0].message).toContain("not valid JSON");
    }
  });

  it("maps a mid-transfer body failure to a recoverable error, never a rejection", async () => {
    // a 200 whose body stream dies must not strand the caller's in-flight
    // state behind an unhandled rejection
    const brokenBody: typeof fetch = async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.error(new Error("connection reset"));
          },
        }),
        { status: 200, headers: { "content-type": "text/markdown" } },
      );
    const result = await downloadReport(fileOf("{}"), fileOf("{}"), "markdown", brokenBody);
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("mid-transfer");
  });
});

describe("health", () => {
  it("returns ok on 200", async () => {
    const result = await health(fetchReturning(200, { status: "ok", api_version: "1.0.0" }));
    expect(result.kind).toBe("ok");
  });
});
