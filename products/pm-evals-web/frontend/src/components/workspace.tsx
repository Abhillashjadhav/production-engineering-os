"use client";

// The S-1 → S-2/S-3 wiring: the upload form hands its comparison (plus the
// exact files it came from) upward, and the dashboard, downloads (J-8), and
// trace explorer render beneath it. Reset or re-selection clears them — a
// stale verdict is never left standing next to new inputs.

import { useState } from "react";

import { Dashboard } from "@/components/dashboard";
import { DownloadPanel } from "@/components/download-panel";
import { TraceExplorer } from "@/components/trace-explorer";
import { UploadForm, type ComparisonHandoff } from "@/components/upload-form";

interface WorkspaceProps {
  // Injected in tests so the real components run against a fake network.
  fetcher?: typeof fetch;
}

export function Workspace({ fetcher }: WorkspaceProps) {
  const [handoff, setHandoff] = useState<ComparisonHandoff | null>(null);
  const [loading, setLoading] = useState(false);
  return (
    <>
      <UploadForm fetcher={fetcher} onComparison={setHandoff} onLoadingChange={setLoading} />
      {handoff !== null && (
        <>
          <Dashboard comparison={handoff.comparison} />
          <DownloadPanel
            baseline={handoff.baseline}
            candidate={handoff.candidate}
            fetcher={fetcher}
          />
        </>
      )}
      {(loading || handoff !== null) && (
        <TraceExplorer comparison={handoff?.comparison ?? null} loading={loading} />
      )}
    </>
  );
}
