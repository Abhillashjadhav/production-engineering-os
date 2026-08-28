import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL's automatic cleanup only registers when the runner exposes a global
// afterEach (vitest `globals: true`, which this project does not enable) —
// without this, each test's DOM leaks into the next.
afterEach(() => {
  cleanup();
});
