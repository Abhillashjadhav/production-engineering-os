// UX F-3 / GATE-1: the S-3 "Filter changed traces" input and the "Show"
// direction select were exercised only in jsdom; every browser path clicked a
// trace directly, so the filter half of J-7 could regress in the real build
// while browser E2E still reported green. This drives both controls in the real
// build against the REGRESSION fixture, whose changed traces span both
// directions: T-001/T-002/T-006 regressed, T-003 improved (4 total).
import { expect, test } from "@playwright/test";

import { compareFixtures } from "./helpers";

test("S-3 changed-trace filters narrow the browser view (J-7)", async ({ page }) => {
  await page.goto("/");
  await compareFixtures(page); // REGRESSION: 4 changed traces, mixed direction

  const traces = page.getByRole("region", { name: /changed traces/i });
  const list = traces.getByRole("list", { name: /changed traces/i });

  // All four changed traces are shown before any filtering.
  await expect(list.getByRole("button")).toHaveCount(4);

  // The text filter narrows the list to matching trace ids.
  await traces.getByLabel(/filter changed traces/i).fill("T-006");
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(list.getByRole("button", { name: /^T-006/ })).toBeVisible();

  // A filter that matches nothing shows the declared empty state.
  await traces.getByLabel(/filter changed traces/i).fill("T-999");
  await expect(traces.getByText(/no changed traces match the filter/i)).toBeVisible();

  // Clear the text filter, then filter by direction via the Show select.
  await traces.getByLabel(/filter changed traces/i).fill("");
  await traces.getByLabel(/^show$/i).selectOption("regressed");
  await expect(list.getByRole("button")).toHaveCount(3); // T-001, T-002, T-006
  await expect(list.getByRole("button", { name: /^T-003/ })).toHaveCount(0);

  await traces.getByLabel(/^show$/i).selectOption("improved");
  await expect(list.getByRole("button")).toHaveCount(1); // T-003
  await expect(list.getByRole("button", { name: /^T-003/ })).toBeVisible();

  await traces.getByLabel(/^show$/i).selectOption("all");
  await expect(list.getByRole("button")).toHaveCount(4);
});
