// Screen S-1 shell: the J-1 explainer is real product surface.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "@/app/page";

describe("home page", () => {
  it("explains the product in plain words with all three verdicts", () => {
    render(<HomePage />);
    expect(
      screen.getByRole("heading", { name: /compare eval runs before you release/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/PROCEED/)).toBeInTheDocument();
    expect(screen.getByText(/HOLD/)).toBeInTheDocument();
    expect(screen.getByText(/INSUFFICIENT_EVIDENCE/)).toBeInTheDocument();
    expect(screen.getByText(/never stored/i)).toBeInTheDocument();
  });
});
