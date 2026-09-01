// PD-V3-09: automated accessibility checks (axe) pass on every screen of the
// primary journey — against the REAL production build and REAL backend.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { compareFixtures, openComparisonWorkbench } from "./helpers";

async function expectNoViolations(page: Parameters<typeof compareFixtures>[0]): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      nodes: v.nodes.map((n) => n.target),
    })),
  ).toEqual([]);
}

test("S-1 initial screen (J-1/J-2) is axe-clean", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /see the exact issue/i })).toBeVisible();
  await expect(page.getByText(/no production eval data received/i)).toBeVisible();
  await expect(page.getByText(/dj-linkedin-pm-bengaluru-042/i)).toHaveCount(0);
  await expectNoViolations(page);
});

test("S-1 with client-side validation errors (J-4) is axe-clean", async ({ page }) => {
  await page.goto("/");
  await openComparisonWorkbench(page);
  await page.getByLabel(/baseline/i).setInputFiles({
    name: "broken.json",
    mimeType: "application/json",
    buffer: Buffer.from("{broken"),
  });
  await expect(page.getByText(/not valid JSON in this browser's reading/)).toBeVisible();
  await expectNoViolations(page);
});

test("S-2 dashboard and downloads after a real comparison (J-6/J-8) are axe-clean", async ({
  page,
}) => {
  await page.goto("/");
  await compareFixtures(page);
  await expect(page.getByRole("table", { name: /criterion-level deltas/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /markdown/i })).toBeVisible();
  await expectNoViolations(page);
});

test("S-3 trace detail (J-7) is axe-clean", async ({ page }) => {
  await page.goto("/");
  await compareFixtures(page);
  const traceButton = page.getByRole("button", { name: /^T-006$/ });
  await traceButton.click();
  const detail = page.getByRole("region", { name: /trace T-006 detail/i });
  await expect(detail).toBeVisible();
  // The expanded button is programmatically linked to the region it reveals
  // (aria-controls → the detail's id), so AT users can follow the relationship.
  const controls = await traceButton.getAttribute("aria-controls");
  expect(controls).toBe(await detail.getAttribute("id"));
  expect(controls).toBeTruthy();
  await expectNoViolations(page);
});
