// Parity guard (dogfood arch F-3). The client pre-validation mirror
// (src/lib/validate.ts) hardcodes MAX_UPLOAD_BYTES and FORMAT_VERSION — a LOCKED
// design decision so a PM gets instant feedback before uploading. This test
// keeps that coupling honest: if the backend changes either constant and the
// mirror is not updated with it, the client would block a file the server
// accepts (or admit one it rejects), silently breaking the mirror's documented
// fail-open contract. It reads the backend source as the single source of truth.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { FORMAT_VERSION, MAX_UPLOAD_BYTES, preValidateFile } from "@/lib/validate";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_SRC = path.resolve(HERE, "../../backend/src");

// Read a module-level integer constant from a Python source file, evaluating a
// simple product of integer literals (digits and `*` only) and ignoring any
// trailing comment. Anchored to column 0 so it matches the definition, never a
// usage.
function backendConstant(relPath: string, name: string): number {
  const text = readFileSync(path.join(BACKEND_SRC, relPath), "utf8");
  const match = text.match(new RegExp(`^${name}\\s*=\\s*([^#\\n]+)`, "m"));
  if (match === null) {
    throw new Error(`${name} not found at column 0 in ${relPath}`);
  }
  const value = match[1]
    .trim()
    .split("*")
    .reduce((product, factor) => product * Number.parseInt(factor.trim(), 10), 1);
  if (!Number.isInteger(value)) {
    throw new Error(`could not parse ${name} in ${relPath}: '${match[1].trim()}'`);
  }
  return value;
}

describe("client mirror stays in parity with the backend (arch F-3)", () => {
  it("MAX_UPLOAD_BYTES matches the backend per-file size cap", () => {
    expect(MAX_UPLOAD_BYTES).toBe(backendConstant("pm_evals_api/app.py", "MAX_UPLOAD_BYTES"));
  });

  it("FORMAT_VERSION matches the backend format version", () => {
    expect(FORMAT_VERSION).toBe(backendConstant("pm_evals_compare/models.py", "FORMAT_VERSION"));
  });

  it("the oversized-file message reports the cap derived from MAX_UPLOAD_BYTES", () => {
    // The displayed limit must be computed from the constant, not a separate
    // hardcoded number that could survive a cap change and mislead the user.
    const expectedMb = Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024));
    const message = preValidateFile("baseline", MAX_UPLOAD_BYTES + 1, "").issues[0].message;
    expect(message).toContain(`${expectedMb} MB limit`);
  });
});
