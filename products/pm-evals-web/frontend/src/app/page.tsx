import { MonitoringDashboard } from "@/components/monitoring-dashboard";
import { Workspace } from "@/components/workspace";
import { Explainer } from "@/lib/explainer";

// The explainer (J-1) plus the full compare workspace: S-1 upload journey
// (J-2..J-5, J-9) feeding the S-2 dashboard (J-6) and S-3 trace explorer
// (J-7). Downloads (J-8) land in PR 9.
export default function HomePage() {
  return (
    <main>
      <MonitoringDashboard />
      <details className="comparison-workbench">
        <summary>
          <span>Compare two eval runs</span>
          <small>Existing release-check workflow</small>
        </summary>
        <div className="comparison-content">
          <Explainer />
          <Workspace />
        </div>
      </details>
    </main>
  );
}
