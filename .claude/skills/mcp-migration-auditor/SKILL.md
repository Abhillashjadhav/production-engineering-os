---
name: mcp-migration-auditor
description: "Iterate-stage skill: scans an MCP configuration against the 2026 spec revision and returns per-server BREAKS/DEGRADED/SAFE verdicts — every finding citing both the config line and the spec clause. Use when spec readiness is the question — 'audit our MCP config for the 2026 spec', 'will our connectors break when the spec lands', 'spec-readiness scan on this .mcp.json' — or when /pm routes such a request here. Do NOT use for MCP context-cost audits, for debugging broken connections, for server installation, or for what-changed-in-the-spec questions with no config to audit."
argument-hint: "<the MCP config (.mcp.json or equivalent) + the spec baseline you trust (or let the skill fetch the current spec text)>"
---

# MCP Migration Auditor

Config on one side, spec on the other, and every finding holds a line from each. A migration verdict that can't quote both is a guess wearing a checklist.

## Verification gates (defined first; output is blocked until all pass)

- **G1 — Double citation:** every finding cites the config line(s) it applies to AND the spec clause it violates or satisfies — quoted, from the provided baseline or spec text actually fetched this session. One-sided findings fail.
- **G2 — Spec honesty:** no clause is asserted that can't be quoted. Recollected-but-unquotable spec changes are tagged `unverified: confirm against current spec` and excluded from verdicts. Invented deprecation dates, clauses, or timelines fail.
- **G3 — One verdict per server, fixes concrete:** each server gets exactly one of BREAKS / DEGRADED / SAFE; every non-SAFE finding carries the concrete fix (what the line becomes) and an effort class — "update it" is not a fix.

## Steps

1. **Number the config and inventory the servers:** transport, auth, capabilities per server — these are the audit's subjects, cited by line.
2. **Fix the spec baseline.** Use the user-provided baseline verbatim, or fetch the current spec/changelog text and quote from it. The baseline's clauses are the only law this audit applies; its version/date is stated in the header.
3. **Audit each server against each relevant clause:** transport (removed/replaced transports), auth (required patterns, deprecated token styles), capabilities/lifecycle changes. Per check, write the citation pair — config line + clause — and the consequence at spec-enforcement time.
4. **Assign verdicts:** BREAKS (a clause the server violates fatally at enforcement) · DEGRADED (works but on deprecated/discouraged patterns with a stated horizon) · SAFE (compliant, cited). The worst applicable finding sets the server's verdict.
5. **Write the fixes:** the concrete config change (L2's `"transport": "sse"` → the streamable-HTTP form), migration order (breaks first), and effort class per fix (config-only / server-upgrade / auth-infrastructure). Unknowns about the server binary's capabilities are questions to its owner, not assumptions.
6. **Gate pass.** Every finding double-cited (G1), every clause quotable with unverified items quarantined (G2), one verdict per server with concrete fixes (G3). Fix and re-run; maximum 2 repair loops, then report the failure.

## Output format

```
MCP MIGRATION AUDIT (spec baseline: <version/date, as provided/fetched>)
| server  | verdict  | config line | spec clause | fix | effort |
| tickets | BREAKS   | L2 "transport": "sse" | "SSE transport removed; streamable HTTP replaces it" | L2 → {"transport": "streamable-http", "url": …} | config-only, if server binary supports it — confirm with owner |
| docs    | SAFE     | L3 stdio | "stdio unchanged" | — | — |
| crm     | DEGRADED | L5 static bearer token | "OAuth resource-server pattern required; static bearer deprecated" | move to OAuth RS flow; rotate the hardcoded token NOW regardless | auth-infrastructure |
MIGRATION ORDER: tickets (breaks) → crm auth (deprecated + a live credential in config) → none for docs.
UNVERIFIED (not in verdicts): <any recollected clause without quotable text — confirm against current spec>
GATE CHECK: G1 pass (n/n double-cited) · G2 pass (0 unquotable clauses in verdicts) · G3 pass
```

## Hard rules

1. Both citations, always. The config line without the clause is a lint; the clause without the line is trivia; the audit is the pair.
2. Never assert spec content from memory. Quote the provided baseline or fetched text, or tag it unverified and keep it out of verdicts.
3. One verdict per server — the worst finding wins; a server is never "mostly safe".
4. Security observations found in passing (a hardcoded credential) are flagged with the finding even when the spec clause is about something else — but labeled as out-of-scope-of-spec, in-scope-of-sanity.

## Limitations

- The audit is config-level: it verifies what the config declares, not what the server binary actually implements — binary capabilities are confirm-with-owner questions.
- Spec interpretation follows the quoted clauses; ambiguous clauses are flagged with both readings rather than silently resolved.
- A baseline the user provides is trusted as given; if it's stale, the audit is faithfully stale — the header's version/date line exists so the reader can check.
- Enforcement timing is quoted when the spec/changelog states it and otherwise absent — no invented deadlines.
