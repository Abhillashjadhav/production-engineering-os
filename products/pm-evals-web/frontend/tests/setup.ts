import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom's Blob lacks text() under some supported Node versions. Keep the
// browser-facing download tests runtime-independent instead of weakening them.
if (typeof Blob.prototype.text !== "function") {
  Object.defineProperty(Blob.prototype, "text", {
    configurable: true,
    value(this: Blob): Promise<string> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ""));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(this);
      });
    },
  });
}

// RTL's automatic cleanup only registers when the runner exposes a global
// afterEach (vitest `globals: true`, which this project does not enable) —
// without this, each test's DOM leaks into the next.
afterEach(() => {
  cleanup();
});
