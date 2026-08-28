// Shared journey helpers: the REAL fixtures drive the REAL app end to end.
import path from "node:path";

import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

const FIXTURES = path.resolve(__dirname, "..", "..", "fixtures");

export const BASELINE_FIXTURE = path.join(FIXTURES, "baseline.json");
export const REGRESSION_FIXTURE = path.join(FIXTURES, "candidate_regression.json");
export const IMPROVED_FIXTURE = path.join(FIXTURES, "candidate_improved.json");

export async function openComparisonWorkbench(page: Page): Promise<void> {
  const workbench = page.locator("details.comparison-workbench");
  if ((await workbench.getAttribute("open")) === null) {
    await workbench.getByText("Compare two eval runs", { exact: true }).click();
  }
  await expect(page.getByRole("heading", { name: /compare eval runs/i })).toBeVisible();
}

// File selection uses setInputFiles: the OS file dialog is not scriptable
// from any test framework — everything after selection stays keyboard/AT
// verifiable.
export async function compareFixtures(
  page: Page,
  candidate: string = REGRESSION_FIXTURE,
): Promise<void> {
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles(BASELINE_FIXTURE);
  await page.getByLabel(/candidate/i).setInputFiles(candidate);
  const button = page.getByRole("button", { name: /compare runs/i });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByRole("region", { name: /release verdict/i })).toBeVisible();
}
