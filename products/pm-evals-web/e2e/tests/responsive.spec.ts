// PD-V3-09: the journey works at a phone viewport (iPhone 12 profile,
// 390x844) with no horizontal page overflow — the criterion table scrolls
// inside its own container, never the page.
import { expect, test } from "@playwright/test";

import { compareFixtures } from "./helpers";

async function expectNoHorizontalOverflow(
  page: Parameters<typeof compareFixtures>[0],
): Promise<void> {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

test("the journey completes at a phone viewport without horizontal overflow", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /compare eval runs/i })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await compareFixtures(page);
  await expect(page.getByRole("table", { name: /criterion-level deltas/i })).toBeVisible();
  await expectNoHorizontalOverflow(page); // the deltas table must not widen the page

  await page.getByRole("button", { name: /^T-006$/ }).click();
  await expect(page.getByRole("region", { name: /trace T-006 detail/i })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("the S-3 criterion table does not overflow the page at 375px", async ({ page }) => {
  // The contract's declared mobile width. The per-criterion table scrolls in
  // its own container (.table-scroll), so the page itself never scrolls sideways.
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await compareFixtures(page);
  await page.getByRole("button", { name: /^T-006$/ }).click();
  const detail = page.getByRole("region", { name: /trace T-006 detail/i });
  await expect(detail.getByRole("table")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
