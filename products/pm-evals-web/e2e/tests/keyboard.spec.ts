// PD-V3-09: the primary journey is completable with keyboard only, with
// visible focus. File selection uses setInputFiles (the OS dialog is not
// scriptable); every subsequent step is driven by Tab/Enter alone.
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { BASELINE_FIXTURE, REGRESSION_FIXTURE } from "./helpers";

// Tab (or Shift+Tab) until the focused element matches, bounded so a broken
// tab order fails loudly instead of looping forever.
async function tabTo(
  page: Page,
  predicate: string,
  options: { maxTabs?: number; shift?: boolean } = {},
): Promise<void> {
  const { maxTabs = 40, shift = false } = options;
  for (let i = 0; i < maxTabs; i += 1) {
    await page.keyboard.press(shift ? "Shift+Tab" : "Tab");
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

  // J-7: TAB all the way to a trace button (proves reachability, not just
  // activability) and open its detail
  await tabTo(page, ".trace-list button");
  const traceId = await page.evaluate(() => document.activeElement?.textContent ?? "");
  expect(traceId).toMatch(/^T-\d+/);
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("region", { name: new RegExp(`trace ${traceId} detail`, "i") }),
  ).toBeVisible();

  // J-8: Shift+Tab back to a download button and download by keyboard
  await tabTo(page, ".download-buttons button", { shift: true });
  const downloadEvent = page.waitForEvent("download");
  await page.keyboard.press("Enter");
  const file = await downloadEvent;
  expect(file.suggestedFilename()).toMatch(/^eval-comparison\.(md|json)$/);

  // J-9: Shift+Tab further back to Start a new comparison
  await tabTo(page, ".compare-status button", { shift: true });
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
