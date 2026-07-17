// J-1: a simple explanation of what the product does, for a non-technical PM.
export function Explainer() {
  return (
    <header>
      <h1>Compare eval runs before you release</h1>
      <p>
        Upload the eval results from your current version (the baseline) and
        from the change you are considering (the candidate). pm-evals compares
        them trace by trace and tells you whether the change looks safe to
        release — with the evidence behind every number.
      </p>
      <ul>
        <li>
          <strong>PROCEED</strong> — nothing required got worse and every
          guardrail passed.
        </li>
        <li>
          <strong>HOLD</strong> — something a release gate protects newly
          fails, or a guardrail was violated.
        </li>
        <li>
          <strong>INSUFFICIENT_EVIDENCE</strong> — the files are valid but do
          not contain enough comparable results to judge safely.
        </li>
      </ul>
      <p>
        Files are processed in memory and never stored. No sign-in, no data
        leaves this app.
      </p>
    </header>
  );
}
