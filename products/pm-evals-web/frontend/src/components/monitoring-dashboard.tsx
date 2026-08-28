"use client";

import { useEffect, useMemo, useState } from "react";

import {
  monitoringOverview,
  type Incident,
  type MonitoringOverview,
  type ProductHealth,
  type TrendPoint,
} from "@/lib/api";

interface MonitoringDashboardProps {
  fetcher?: typeof fetch;
}

function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function humanize(value: string): string {
  const words = value.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(
    new Date(value),
  );
}

function currentTime(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

function resultValue(value: number | null, unit: string): string {
  if (value === null) return "Unavailable";
  if (unit === "ratio") return `${(value * 100).toFixed(0)}%`;
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ""}`;
}

function magnitude(incident: Incident): string {
  if (incident.regression_magnitude === null) return "Difference unavailable";
  if (incident.unit === "ratio") {
    return `${(incident.regression_magnitude * 100).toFixed(0)} percentage points`;
  }
  return `${incident.regression_magnitude.toFixed(2)}${incident.unit ? ` ${incident.unit}` : ""}`;
}

function healthClass(health: ProductHealth["health"]): string {
  return `health-${health.toLowerCase()}`;
}

function actionLabel(action: Incident["maintenance"]["eval_action"]): string {
  if (action === "KEEP") return "Keep as-is";
  if (action === "REVIEW_AFTER_ADJUDICATION") return "Review after confirmation";
  return "Investigate first";
}

function productIdentity(product: Pick<ProductHealth, "product_id" | "environment">): string {
  return `${product.product_id}\u001f${product.environment}`;
}

function Sparkline({ points }: { points: TrendPoint[] }) {
  const width = 260;
  const height = 72;
  const padding = 6;
  const coordinates = points.map((point, index) => {
    const x =
      points.length === 1
        ? width / 2
        : padding + (index / (points.length - 1)) * (width - padding * 2);
    const y = padding + (1 - point.pass_rate) * (height - padding * 2);
    return { ...point, x, y };
  });
  const path = coordinates.map((point) => `${point.x},${point.y}`).join(" ");
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Pass-rate trend from ${pct(points[0]?.pass_rate ?? 0)} to ${pct(points.at(-1)?.pass_rate ?? 0)}`}
    >
      <line x1="6" x2="254" y1="66" y2="66" className="sparkline-axis" />
      <polyline points={path} className="sparkline-line" />
      {coordinates.map((point) => (
        <circle
          key={point.observed_at}
          cx={point.x}
          cy={point.y}
          r="4"
          className={`sparkline-point ${point.health === "FAILING" ? "sparkline-point-failing" : ""}`}
        >
          <title>{`${shortDate(point.observed_at)}: ${pct(point.pass_rate)} · ${point.health}`}</title>
        </circle>
      ))}
    </svg>
  );
}

function ProductCard({
  product,
  trend,
  selected,
  onSelect,
}: {
  product: ProductHealth;
  trend: TrendPoint[];
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`product-card ${selected ? "product-card-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span className="product-card-topline">
        <span>
          <span className="product-name">{product.display_name}</span>
          <span className="product-meta">{product.environment} · {product.version}</span>
        </span>
        <span className={`health-pill ${healthClass(product.health)}`}>{product.health}</span>
      </span>
      <Sparkline points={trend} />
      <span className="product-card-footer">
        <span><strong>{product.pass_count}</strong> passing</span>
        <span><strong>{product.fail_count}</strong> failing</span>
        <span>{currentTime(product.observed_at)}</span>
      </span>
    </button>
  );
}

function IncidentCard({ incident }: { incident: Incident }) {
  return (
    <article className="incident-card">
      <div className="incident-rail" aria-hidden="true" />
      <div className="incident-content">
        <div className="incident-heading">
          <div>
            <p className="eyebrow">Likely starting failure</p>
            <h3>{incident.case.display_name}</h3>
            <code className="case-id">Case {incident.case.case_id}</code>
          </div>
          <span className={`confidence-pill confidence-${incident.cause_confidence.toLowerCase()}`}>
            {humanize(incident.cause_confidence)} cause
          </span>
        </div>

        <p className="case-context">
          <span><strong>Environment:</strong> {incident.environment}</span>
          <span><strong>Use case:</strong> {incident.case.use_case_id}</span>
          <span><strong>Segment:</strong> {incident.case.segment}</span>
          <span><strong>Check:</strong> {humanize(incident.layer)} · {humanize(incident.concern)}</span>
        </p>

        <div className="result-comparison" aria-label="Current and expected result">
          <div className="current-result">
            <span>Current result</span>
            <strong>{resultValue(incident.current_value, incident.unit)}</strong>
            <small>{incident.current_summary}</small>
          </div>
          <div>
            <span>Expected result</span>
            <strong>{resultValue(incident.expected_value, incident.unit)}</strong>
            <small>{incident.expected_summary}</small>
          </div>
          <div>
            <span>Pass bar</span>
            <strong>{resultValue(incident.threshold, incident.unit)}</strong>
            <small>The minimum acceptable result for this check.</small>
          </div>
          <div>
            <span>Difference</span>
            <strong>{magnitude(incident)}</strong>
            <small>{incident.comparison_label}: {incident.comparison_run_id}</small>
          </div>
        </div>

        <div className="diagnosis-columns">
          <section className="diagnosis-box" aria-labelledby={`${incident.incident_id}-cause`}>
            <p className="step-label">1 · Why this likely happened</p>
            <h4 id={`${incident.incident_id}-cause`}>{humanize(incident.cause_category)}</h4>
            <p>{incident.cause_reason}</p>
            <div className="evidence-level">
              Evidence: <strong>{humanize(incident.evidence_level)}</strong>
            </div>
            {incident.changes_since_comparison.length > 0 && (
              <div className="change-list">
                <span>Changed since the good run</span>
                {incident.changes_since_comparison.map((change) => (
                  <div key={change.dimension}>
                    <strong>{humanize(change.dimension)}</strong>
                    <code>{change.previous} → {change.current}</code>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="diagnosis-box fix-box" aria-labelledby={`${incident.incident_id}-fix`}>
            <p className="step-label">2 · Go here first</p>
            <h4 id={`${incident.incident_id}-fix`}>{incident.fix_location}</h4>
            <dl className="fix-details">
              <div><dt>Owner</dt><dd>{incident.owner_id}</dd></div>
              <div><dt>Component</dt><dd>{incident.component_id}</dd></div>
              <div><dt>Stage</dt><dd>{incident.stage_id}</dd></div>
              <div><dt>Parameter</dt><dd>{incident.parameter_id}</dd></div>
            </dl>
            <p className="fix-action">{incident.remediation.action}</p>
          </section>
        </div>

        <section className="maintenance-box" aria-labelledby={`${incident.incident_id}-maintenance`}>
          <div>
            <p className="step-label">3 · Change the eval or approved cases?</p>
            <h4 id={`${incident.incident_id}-maintenance`}>Not from the score alone</h4>
            <p>{incident.maintenance.reason}</p>
          </div>
          <div className="maintenance-actions">
            <span>Eval <strong>{actionLabel(incident.maintenance.eval_action)}</strong></span>
            <span>Approved cases <strong>{actionLabel(incident.maintenance.golden_dataset_action)}</strong></span>
          </div>
        </section>

        <div className="incident-footer">
          <span>
            <strong>{incident.downstream_observation_ids.length}</strong> downstream symptoms hidden from the starting-failure count
          </span>
          <details className="evidence-disclosure">
            <summary>Show evidence references</summary>
            {incident.evidence_refs.map((evidence) => (
              <div key={evidence.sha256} className="evidence-reference">
                <code>{evidence.uri}</code>
                <code>{evidence.sha256.slice(0, 22)}…</code>
              </div>
            ))}
          </details>
        </div>
      </div>
    </article>
  );
}

function CoverageMatrix({
  products,
  axis,
}: {
  products: ProductHealth[];
  axis: "layers" | "concerns";
}) {
  const names = Array.from(
    new Set(products.flatMap((product) => product[axis].map((item) => item.name))),
  );
  return (
    <div className="coverage-matrix table-scroll">
      <table>
        <thead>
          <tr>
            <th scope="col">{axis === "layers" ? "Evaluation layer" : "What it protects"}</th>
            {products.map((product) => (
              <th scope="col" key={productIdentity(product)}>
                {product.display_name} · {product.environment}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {names.map((name) => (
            <tr key={name}>
              <th scope="row">{humanize(name)}</th>
              {products.map((product) => {
                const result = product[axis].find((item) => item.name === name);
                return (
                  <td key={productIdentity(product)}>
                    {result ? (
                      <span className={`coverage-status ${healthClass(result.health)}`}>
                        {humanize(result.health)}
                      </span>
                    ) : <span className="not-covered">Not covered</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MonitoringDashboard({ fetcher }: MonitoringDashboardProps) {
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedProduct, setSelectedProduct] = useState<string>("all");
  const [requestKey, setRequestKey] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    void monitoringOverview(fetcher).then((result) => {
      if (!active) return;
      if (result.kind === "ok") setOverview(result.value);
      else setError(result.kind === "error" ? result.message : "Monitoring could not load.");
    });
    return () => { active = false; };
  }, [fetcher, requestKey]);

  const filteredIncidents = useMemo(
    () => overview?.incidents.filter(
      (incident) => selectedProduct === "all" || productIdentity(incident) === selectedProduct,
    ) ?? [],
    [overview, selectedProduct],
  );

  if (overview === null && error === null) {
    return (
      <section className="monitoring-shell monitoring-loading" aria-label="Loading eval health">
        <div className="loading-line" /><div className="loading-grid"><div /><div /><div /></div>
      </section>
    );
  }

  if (overview === null) {
    return (
      <section className="monitoring-shell monitoring-error" aria-labelledby="monitoring-error-heading">
        <p className="eyebrow">Eval observability</p>
        <h1 id="monitoring-error-heading">Production health is unavailable</h1>
        <p>{error}</p>
        <button type="button" onClick={() => setRequestKey((key) => key + 1)}>Try again</button>
      </section>
    );
  }

  const healthyProducts = overview.products.filter((product) => product.health === "HEALTHY").length;
  const selectedProducts = overview.products.filter(
    (product) => selectedProduct === "all" || productIdentity(product) === selectedProduct,
  );
  const selectionNeedsEvidence = selectedProducts.some(
    (product) => product.health !== "HEALTHY",
  );
  const exactCases = new Set(
    overview.incidents.map(
      (incident) => `${productIdentity(incident)}\u001f${incident.case.case_id}`,
    ),
  ).size;
  const metrics = overview.attribution_metrics;

  return (
    <section className="monitoring-shell" aria-labelledby="monitoring-heading">
      <header className="monitoring-header">
        <div>
          <p className="brand-kicker"><span className="brand-mark">E</span> PM EVALS / PRODUCTION</p>
          <h1 id="monitoring-heading">See the exact failure.<br />Start in the right place.</h1>
          <p className="monitoring-subtitle">
            Case-level health from input to outcome, with quality and risk checks at every layer.
          </p>
        </div>
        <div className="run-context">
          <span className={`mode-pill ${overview.mode === "PLANTED_DEMO" ? "mode-demo" : "mode-live"}`}>
            {overview.mode === "PLANTED_DEMO" ? "Planted demo run" : "Live observations"}
          </span>
          <span>Updated {currentTime(overview.generated_at)}</span>
        </div>
      </header>

      {overview.mode === "PLANTED_DEMO" && (
        <div className="demo-banner" role="note">
          <strong>Simulation, not production.</strong> One known Dream Job connector failure is planted to prove exact-case localization, controlled-replay attribution, and downstream suppression.
        </div>
      )}

      <div className="metric-strip" aria-label="Monitoring metrics">
        <div><span>Product health</span><strong>{healthyProducts}/{overview.products.length}</strong><small>healthy now</small></div>
        <div><span>Failed cases</span><strong>{exactCases}</strong><small>exact cases to inspect</small></div>
        <div><span>Correct localization</span><strong>{pct(metrics.correctly_localized_rate)}</strong><small>{metrics.known_cause_sample_size} known-cause sample</small></div>
        <div className="guardrail-metric"><span>False attribution</span><strong>{pct(metrics.false_attribution_rate)}</strong><small>target &lt;2% · not proven</small></div>
      </div>

      <div className="section-heading">
        <div><p className="eyebrow">Today</p><h2>Product health</h2></div>
        <button
          type="button"
          className={`all-products-filter ${selectedProduct === "all" ? "active" : ""}`}
          onClick={() => setSelectedProduct("all")}
          aria-pressed={selectedProduct === "all"}
        >All products</button>
      </div>
      <div className="product-grid">
        {overview.products.map((product) => (
          <ProductCard
            key={productIdentity(product)}
            product={product}
            trend={overview.trend.filter(
              (point) => productIdentity(point) === productIdentity(product),
            )}
            selected={selectedProduct === productIdentity(product)}
            onSelect={() => setSelectedProduct(productIdentity(product))}
          />
        ))}
      </div>

      <div className="dashboard-grid">
        <section aria-labelledby="incidents-heading" className="incidents-panel">
          <div className="section-heading compact">
            <div><p className="eyebrow">Diagnosis</p><h2 id="incidents-heading">Where to start</h2></div>
            <span className="section-count">{filteredIncidents.length}</span>
          </div>
          {filteredIncidents.length ? filteredIncidents.map((incident) => (
            <IncidentCard key={incident.incident_id} incident={incident} />
          )) : (
            <div className="empty-state">
              <strong>
                {selectionNeedsEvidence
                  ? "No confirmed starting point yet."
                  : "No starting failure found."}
              </strong>
              <span>
                {selectionNeedsEvidence
                  ? "Evidence is blocked, incomplete, or still needs investigation."
                  : "Selected products are within their approved bars."}
              </span>
            </div>
          )}
        </section>

        <aside className="confidence-panel" aria-labelledby="confidence-heading">
          <p className="eyebrow">Trust calibration</p>
          <h2 id="confidence-heading">How much can we claim?</h2>
          <div className="confidence-number">{metrics.known_cause_sample_size}</div>
          <p>known-cause case tested</p>
          <div className="confidence-rule" />
          <strong className="not-proven">Production guardrail not proven</strong>
          <p>{metrics.label}</p>
          <dl className="confidence-details">
            <div><dt>Cases localized</dt><dd>{pct(metrics.attribution_coverage)}</dd></div>
            <div><dt>False-attribution target</dt><dd>&lt;2%</dd></div>
            <div><dt>Human-confirmed production cases</dt><dd>{metrics.production_adjudicated_sample_size}</dd></div>
          </dl>
        </aside>
      </div>

      <section className="coverage-panel" aria-labelledby="coverage-heading">
        <div className="section-heading compact">
          <div><p className="eyebrow">Coverage</p><h2 id="coverage-heading">What is actually being tested?</h2></div>
          <span className="coverage-note">Missing does not mean healthy</span>
        </div>
        <div className="coverage-grid">
          <div><h3>Where we test</h3><CoverageMatrix products={overview.products} axis="layers" /></div>
          <div><h3>What we protect</h3><CoverageMatrix products={overview.products} axis="concerns" /></div>
        </div>
      </section>
    </section>
  );
}
