"use client";

// The S-1 → S-2/S-3 wiring: the upload form reports its comparison up, and
// the dashboard + trace explorer render beneath it. Reset or re-selection
// clears them — a stale verdict is never left standing next to new inputs.

import { useState } from "react";

import { Dashboard } from "@/components/dashboard";
import { TraceExplorer } from "@/components/trace-explorer";
import { UploadForm } from "@/components/upload-form";
import type { Comparison } from "@/lib/api";

interface WorkspaceProps {
  // Injected in tests so the real components run against a fake network.
  fetcher?: typeof fetch;
}

export function Workspace({ fetcher }: WorkspaceProps) {
  const [comparison, setComparison] = useState<Comparison | null>(null);
  return (
    <>
      <UploadForm fetcher={fetcher} onComparison={setComparison} />
      {comparison !== null && (
        <>
          <Dashboard comparison={comparison} />
          <TraceExplorer comparison={comparison} />
        </>
      )}
    </>
  );
}
