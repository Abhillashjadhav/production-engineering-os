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
