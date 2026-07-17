// Client-side pre-validation (J-4): fast, named feedback that mirrors the
// backend's parser and compatibility rules. The backend stays authoritative —
// these tests pin that the mirror speaks the same language, not that it
// replaces the server.
import { describe, expect, it } from "vitest";

import {
  MAX_UPLOAD_BYTES,
  preValidateFile,
  preValidatePair,
  type PreParsedRun,
} from "@/lib/validate";

const VALID_RUN = JSON.stringify({
  format_version: 1,
  suite: "support-copilot-v2",
  criteria: [{ id: "C-1", name: "Accuracy" }],
  traces: [{ trace_id: "T-1", results: { "C-1": "pass" } }],
});

function parsed(text: string): PreParsedRun {
  const result = preValidateFile("baseline", text.length, text);
  if (result.run === null) throw new Error("fixture must pre-validate");
  return result.run;
}

describe("preValidateFile", () => {
  it("accepts a valid run and extracts suite and ids", () => {
    const result = preValidateFile("baseline", VALID_RUN.length, VALID_RUN);
    expect(result.issues).toEqual([]);
    expect(result.run).not.toBeNull();
    expect(result.run?.suite).toBe("support-copilot-v2");
    expect(result.run?.criterionIds).toEqual(["C-1"]);
    expect(result.run?.traceIds).toEqual(["T-1"]);
  });

  it("refuses a file over the 5 MB cap without parsing it", () => {
    const result = preValidateFile("candidate", MAX_UPLOAD_BYTES + 1, "{}");
    expect(result.run).toBeNull();
    expect(result.issues[0].message).toContain("5 MB");
    expect(result.issues[0].location).toBe("candidate");
  });

  it("names broken JSON the way the backend does", () => {
    const result = preValidateFile("baseline", 7, "{broken");
    expect(result.run).toBeNull();
    expect(result.issues[0].message).toContain("not valid JSON");
  });

  it("refuses a top-level array", () => {
    const result = preValidateFile("baseline", 2, "[]");
    expect(result.run).toBeNull();
    expect(result.issues[0].message).toContain("must be a JSON object");
  });

  it("names an unsupported format_version and states the supported one", () => {
    const text = VALID_RUN.replace('"format_version": 1', '"format_version": 2');
    const result = preValidateFile("baseline", text.length, text);
    expect(result.run).toBeNull();
    expect(result.issues[0].message).toContain("unsupported format_version");
    expect(result.issues[0].message).toContain("supported: 1");
    expect(result.issues[0].location).toBe("baseline.format_version");
  });

  it("requires a suite name", () => {
    const text = JSON.stringify({ format_version: 1, criteria: [], traces: [] });
    const result = preValidateFile("baseline", text.length, text);
    expect(result.run).toBeNull();
    expect(result.issues.some((i) => i.location === "baseline.suite")).toBe(true);
  });

  it("requires criteria and traces to be lists", () => {
    const text = JSON.stringify({ format_version: 1, suite: "s", criteria: "x", traces: 3 });
    const result = preValidateFile("baseline", text.length, text);
    expect(result.run).toBeNull();
    const locations = result.issues.map((i) => i.location);
    expect(locations).toContain("baseline.criteria");
    expect(locations).toContain("baseline.traces");
  });
});

describe("preValidatePair", () => {
  it("returns no issues for a comparable pair", () => {
    expect(preValidatePair(parsed(VALID_RUN), parsed(VALID_RUN))).toEqual([]);
  });

  it("names a suite mismatch in the backend's words", () => {
    const other = parsed(VALID_RUN.replace("support-copilot-v2", "another-suite"));
    const issues = preValidatePair(parsed(VALID_RUN), other);
    expect(issues.some((i) => i.message.includes("suite mismatch"))).toBe(true);
    expect(issues[0].message).toContain("support-copilot-v2");
    expect(issues[0].message).toContain("another-suite");
  });

  it("names a pair sharing no criteria", () => {
    const other = parsed(VALID_RUN.replace('"C-1"', '"C-2"').replace('"C-1":', '"C-2":'));
    const issues = preValidatePair(parsed(VALID_RUN), other);
    expect(issues.some((i) => i.message.includes("share no criteria"))).toBe(true);
  });

  it("names a pair sharing no trace ids", () => {
    const other = parsed(VALID_RUN.replace("T-1", "T-2"));
    const issues = preValidatePair(parsed(VALID_RUN), other);
    expect(issues.some((i) => i.message.includes("share no trace ids"))).toBe(true);
  });
});
