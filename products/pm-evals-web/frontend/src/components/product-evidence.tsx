import type { MonitoringOverview, ProductHealth } from "@/lib/api";

export function ProductEvidence({ products, metrics }: {
  products: ProductHealth[];
  metrics: NonNullable<MonitoringOverview["detection_metrics"]>;
}) {
  const visibleMetrics = metrics.filter((metric) => products.some(
    (product) => product.product_id === metric.product_id && product.environment === metric.environment,
  ));
  return <section className="coverage-panel" aria-label="Product results and independent failure checks">
    <h2>Delivery and evaluation results</h2>
    <p>A delivered result can still have quality failures. Each recorded check remains visible.</p>
    {products.map((product) => <details key={JSON.stringify([product.product_id, product.environment])}>
      <summary>{product.display_name} — Delivery: {product.delivery_outcome ?? "not recorded"}; {product.source_facts?.length ?? 0} recorded facts</summary>
      <div style={{ overflowX: "auto" }}><table>
        <caption>Individual checks, candidates, and repair cycles</caption>
        <thead><tr><th>Check</th><th>Candidate</th><th>Cycle</th><th>Recorded result</th><th>Observed result</th><th>Mode</th><th>Score</th><th>Reasons</th><th>Evidence</th></tr></thead>
        <tbody>{(product.source_facts ?? []).map((fact, index) => <tr key={index}>
          <td>{fact.contract}</td><td>{fact.subject_id}</td><td>{fact.cycle}</td><td>{fact.recorded_status}</td><td>{fact.observed_status}</td><td>{fact.mode}</td><td>{fact.value ?? "unmeasured"}</td><td>{fact.reason_codes?.join(", ") || "not recorded"}</td>
          <td>{fact.evidence_refs?.map((evidence) => <details key={evidence.sha256}><summary>Evidence digest</summary><code>{evidence.sha256}</code><p>The source remains in the product’s private run records.</p></details>)}</td>
        </tr>)}</tbody>
      </table></div>
    </details>)}
    <h2>Independent silent-failure checks</h2>
    <p>Tool trajectory, system, and output are assessed separately. Exactly 90% does not meet the target. Counts describe reviewed cases, not a guarantee about unseen failures.</p>
    {visibleMetrics.length === 0 ? <p>No independent failure reviews recorded. All three layers remain unproven.</p> : <table>
      <caption>Results by product, evidence source, dataset version, and layer</caption>
      <thead><tr><th>Product</th><th>Evidence</th><th>Dataset</th><th>Layer</th><th>Detected</th><th>Missed</th><th>Detection rate</th><th>Result</th></tr></thead>
      <tbody>{visibleMetrics.map((metric) => <tr key={JSON.stringify([metric.product_id, metric.environment, metric.evidence_scope, metric.dataset_version, metric.layer])}>
        <td>{metric.product_id} ({metric.environment})</td><td>{metric.evidence_scope}</td><td>{metric.dataset_version}</td><td>{metric.layer}</td><td>{metric.detected_silent_failures} / {metric.silent_failures}</td><td>{metric.missed_silent_failures}</td><td>{metric.silent_failure_recall === null ? "unproven" : `${(metric.silent_failure_recall * 100).toFixed(1)}%`}</td><td>{metric.status.replaceAll("_", " ").toLowerCase()}</td>
      </tr>)}</tbody>
    </table>}
  </section>;
}
