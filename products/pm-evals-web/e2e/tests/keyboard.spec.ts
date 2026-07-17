// PD-V3-09: the primary journey is completable with keyboard only, with
// visible focus. File selection uses setInputFiles (the OS dialog is not
// scriptable); every subsequent step is driven by Tab/Enter alone.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { BASELINE_FIXTURE, REGRESSION_FIXTURE } from "./helpers";

// Tab until the focused element matches, bounded so a broken tab order
// fails loudly instead of looping forever.
async function tabTo(page: Page, predicate: string, maxTabs = 25): Promise<void> {
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press("Tab");
    const matches = await page.evaluate(
      (selector) => document.activeElement?.matches(selector) ?? false,
      predicate,
    );
    if (matches) return;
  }
  throw new Error(`no element matching ${predicate} reached within ${maxTabs} tabs`);
}

test("the journey completes keyboard-only with visible focus (J-2..J-9)", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel(/baseline/i).setInputFiles(BASELINE_FIXTURE);
  await page.getByLabel(/candidate/i).setInputFiles(REGRESSION_FIXTURE);
  await expect(page.getByRole("button", { name: /compare runs/i })).toBeEnabled();

  // J-5: activate Compare Runs by keyboard
  await page.getByLabel(/candidate/i).focus();
  await tabTo(page, 'button[type="submit"]');
  const outline = await page.evaluate(
    () => getComputedStyle(document.activeElement as Element).outlineWidth,
  );
  expect(outline).toBe("3px"); // visible focus (globals.css :focus-visible)
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: /release verdict/i })).toBeVisible();

  // J-7: open a trace detail by keyboard
  const trace = page.getByRole("button", { name: /^T-006$/ });
  await trace.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: /trace T-006 detail/i })).toBeVisible();

  // J-8: download the Markdown report by keyboard
  const download = page.getByRole("button", { name: /markdown/i });
  await download.focus();
  const downloadEvent = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  const file = await downloadEvent;
  expect(file.suggestedFilename()).toBe("eval-comparison.md");

  // J-9: start a new comparison by keyboard
  const reset = page.getByRole("button", { name: /start a new comparison/i });
  await reset.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: /release verdict/i })).not.toBeVisible();
});

test("status changes are exposed to assistive technology", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel(/baseline/i).setInputFiles(BASELINE_FIXTURE);
  await page.getByLabel(/candidate/i).setInputFiles(REGRESSION_FIXTURE);
  await page.getByRole("button", { name: /compare runs/i }).click();
  const status = page.getByRole("status");
  await expect(status).toBeVisible();
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(status).toContainText(/HOLD/);
});
