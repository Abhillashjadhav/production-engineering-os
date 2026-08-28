// The functional browser journeys (PD-V3-10): every verdict the engine can
// return, the fail-open advisory paths end to end, and download integrity —
// all against the REAL backend and REAL production frontend, no mocks.
// The special fixtures in tests/fixtures/ are engine-verified:
//   thin_*        -> 2 shared traces < min 5    -> INSUFFICIENT_EVIDENCE
//   duplicate_*   -> client-mirror-passable     -> server 422 duplicate id
//   nan_threshold -> browser-unparseable (NaN)  -> server 422 field message
//   utf16_*       -> browser-unparseable bytes  -> server parses, HOLD/incompatible
import path from "node:path";
import fs from "node:fs/promises";

import { expect, test } from "@playwright/test";

import {
  BASELINE_FIXTURE,
  IMPROVED_FIXTURE,
  REGRESSION_FIXTURE,
  compareFixtures,
  openComparisonWorkbench,
} from "./helpers";

const SPECIALS = path.resolve(__dirname, "fixtures");

test("PROCEED journey: improved candidate with payload-true numbers (J-1..J-6)", async ({
  page,
}) => {
  await page.goto("/");
  await compareFixtures(page, IMPROVED_FIXTURE);
  const panel = page.getByRole("region", { name: /release verdict/i });
  await expect(panel).toContainText("PROCEED");
  await expect(page.getByText("+9.4%")).toBeVisible(); // net change from the engine
  await expect(page.getByText("93.8%")).toBeVisible(); // candidate pass rate
  await expect(page.getByText(/^sha256:/).first()).toBeVisible(); // provenance
});

test("HOLD journey: hard-gate regression with trace-level evidence (J-6/J-7)", async ({
  page,
}) => {
  await page.goto("/");
  await compareFixtures(page, REGRESSION_FIXTURE);
  const panel = page.getByRole("region", { name: /release verdict/i });
  await expect(panel).toContainText("HOLD");
  await expect(panel).toContainText(/hard-gate regression/i);
  await expect(panel).toContainText("T-006");
  await expect(panel).toContainText(/guardrail violation/i);
  await page.getByRole("button", { name: /^T-006$/ }).click();
  const detail = page.getByRole("region", { name: /trace T-006 detail/i });
  // S-3: the detail shows EVERY evaluated criterion (not only the flipped one),
  // each with baseline vs candidate results — the contract's purpose for S-3.
  const table = detail.getByRole("table");
  await expect(table).toContainText("C-GROUNDED"); // the regressed hard gate
  await expect(table).toContainText("C-ACCURACY"); // an unchanged criterion, still shown
  const groundedRow = table.getByRole("row", { name: /C-GROUNDED/ });
  await expect(groundedRow).toContainText(/regressed/i);
  await expect(groundedRow).toContainText("fail"); // candidate result rendered
  // the trace's evidence fields are surfaced
  await expect(detail).toContainText(/GDPR data-export request/);
});

test("INSUFFICIENT_EVIDENCE journey: thin pair gets the honest verdict and guidance", async ({
  page,
}) => {
  await page.goto("/");
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles(path.join(SPECIALS, "thin_baseline.json"));
  await page.getByLabel(/candidate/i).setInputFiles(path.join(SPECIALS, "thin_candidate.json"));
  await page.getByRole("button", { name: /compare runs/i }).click();
  const panel = page.getByRole("region", { name: /release verdict/i });
  await expect(panel).toContainText("INSUFFICIENT_EVIDENCE");
  await expect(panel).toContainText(/share more trace ids/i);
});

test("server-only validation: duplicate trace ids pass the client mirror, the server names them (J-4)", async ({
  page,
}) => {
  await page.goto("/");
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles(BASELINE_FIXTURE);
  await page.getByLabel(/candidate/i).setInputFiles(path.join(SPECIALS, "duplicate_trace.json"));
  const button = page.getByRole("button", { name: /compare runs/i });
  await expect(button).toBeEnabled(); // the mirror fails open by design
  await button.click();
  const alert = page.locator('[role="alert"].api-errors');
  await expect(alert).toContainText("duplicate trace_id 'T-001'"); // the server's own words
});

test("advisory journey: a browser-unparseable file submits and the server's field message wins (J-4)", async ({
  page,
}) => {
  await page.goto("/");
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles(path.join(SPECIALS, "nan_threshold.json"));
  await expect(page.getByText(/not valid JSON in this browser's reading/)).toBeVisible();
  await page.getByLabel(/candidate/i).setInputFiles(IMPROVED_FIXTURE);
  const button = page.getByRole("button", { name: /compare runs/i });
  await expect(button).toBeEnabled(); // advisory, never blocking
  await button.click();
  const alert = page.locator('[role="alert"].api-errors');
  // The parser now refuses the non-finite value at read time with a named issue,
  // rather than letting NaN through to a downstream numeric-constraint message.
  await expect(alert).toContainText(/non-finite number/i);
});

test("advisory journey: UTF-16 bytes the browser cannot read reach the server's HOLD verdict", async ({
  page,
}) => {
  await page.goto("/");
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles(BASELINE_FIXTURE);
  await page.getByLabel(/candidate/i).setInputFiles(path.join(SPECIALS, "utf16_candidate.json"));
  await expect(page.getByText(/not valid JSON in this browser's reading/)).toBeVisible();
  const button = page.getByRole("button", { name: /compare runs/i });
  await expect(button).toBeEnabled();
  await button.click();
  const panel = page.getByRole("region", { name: /release verdict/i });
  await expect(panel).toContainText("HOLD");
  await expect(panel).toContainText(/incompatible evidence/i);
  await expect(panel).toContainText(/suite mismatch/); // the engine's named reason
});

test("download integrity: the JSON report matches the on-screen verdict and digests (J-8)", async ({
  page,
}) => {
  await page.goto("/");
  await compareFixtures(page, REGRESSION_FIXTURE);
  const digests = await page.locator("dd code").allTextContents();
  expect(digests).toHaveLength(2);

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: /download json report/i }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("eval-comparison.json");
  const file = await download.path();
  const report = JSON.parse(await fs.readFile(file, "utf8"));
  expect(report.comparison.verdict).toBe("HOLD");
  expect(report.comparison.baseline_digest).toBe(digests[0]);
  expect(report.comparison.candidate_digest).toBe(digests[1]);

  const markdownEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: /download markdown report/i }).click();
  const markdown = await markdownEvent;
  expect(markdown.suggestedFilename()).toBe("eval-comparison.md");
  const markdownText = await fs.readFile((await markdown.path()) as string, "utf8");
  expect(markdownText).toContain("## Verdict: HOLD");
});
