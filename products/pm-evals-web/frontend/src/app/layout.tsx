import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "pm-evals — Compare Eval Runs",
  description:
    "Upload a baseline and a candidate eval-results file, compare them, and get an evidence-backed release verdict.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
