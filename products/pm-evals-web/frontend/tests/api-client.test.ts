// The typed client's error-shape handling (J-4) and result discrimination.
import { describe, expect, it } from "vitest";

import { compareRuns, health } from "@/lib/api";

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

  it("maps 413 to the size-limit message", async () => {
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), fetchReturning(413, { detail: "too big" }));
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("5 MB");
  });

  it("maps network failure to an unreachable error", async () => {
    const failing: typeof fetch = async () => {
      throw new Error("ECONNREFUSED");
    };
    const result = await compareRuns(fileOf("{}"), fileOf("{}"), failing);
    expect(result.kind).toBe("error");
  });
});

describe("health", () => {
  it("returns ok on 200", async () => {
    const result = await health(fetchReturning(200, { status: "ok", api_version: "1.0.0" }));
    expect(result.kind).toBe("ok");
  });
});
