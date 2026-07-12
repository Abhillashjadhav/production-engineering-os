# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/mcp-migration-auditor/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Audit our MCP config for the 2026 spec changes"
T2. "Are our MCP servers ready for the new spec? Config attached"
T3. "Spec-readiness scan on this .mcp.json"
T4. "/pm will our connectors break when the spec lands?" (via orchestrator, config attached)
T5. "MCP migration audit — what breaks, what degrades, what's safe?"

SHOULD NOT FIRE:
N1. "Audit my MCPs for context cost"               (context-economics question, different audit)
N2. "My MCP server won't connect"                  (debugging, not spec readiness)
N3. "Install this MCP server"                       (setup)
N4. "What changed in the MCP spec?"                 (knowledge question, no config to audit)

# Gate 3 — Known-answer

FIXTURE INPUT (config, numbered lines):
L1. { "mcpServers": {
L2.   "tickets": { "transport": "sse", "url": "https://mcp.internal/tickets" },
L3.   "docs":    { "command": "docs-mcp", "args": ["--stdio"] },
L4.   "crm":     { "transport": "streamable-http", "url": "https://crm.example/mcp",
L5.               "auth": { "type": "bearer", "token": "hardcoded-in-config" } }
L6. } }
Spec baseline provided by user: "2026 revision: SSE transport removed (streamable
HTTP replaces it); OAuth resource-server pattern required for remote servers —
static bearer tokens deprecated; stdio unchanged."

EXPECTED OUTPUT PROPERTIES:
1. THE DOUBLE-CITATION GATE: every finding cites BOTH (a) the config line(s) it
   applies to AND (b) the spec clause (from the provided baseline / fetched spec
   text) it violates or satisfies. A finding with only one citation = gate failure.
   Passing form: 'BREAKS — L2 "transport": "sse" vs spec clause "SSE transport
   removed" → migrate to streamable HTTP.'
2. Expected verdicts per server, each with the citation pair:
   - tickets (L2): BREAKS — SSE removed [config L2 + SSE clause]
   - docs (L3): SAFE — stdio unchanged [config L3 + stdio clause]
   - crm (L4-L5): DEGRADED/BREAKS on auth — static bearer vs OAuth resource-server
     clause [config L5 + auth clause]; transport already compliant [L4 + clause]
3. Verdict taxonomy: BREAKS / DEGRADED / SAFE, each server exactly one verdict,
   with the fix per non-SAFE finding (concrete: what L2 becomes, not 'update it').
4. SPEC HONESTY: findings rely only on the provided spec baseline or spec text
   actually fetched this session — a clause the auditor can't quote is flagged
   'unverified: confirm against current spec' and never presented as settled. No
   invented deprecation dates or clauses.
5. Summary table: server · verdict · config line · spec clause · fix · effort class.

PLANTED-FAILURE CASE:
A draft finding 'the docs server (L3) should migrate off stdio since the spec is
moving everything to HTTP' — a clause that exists in neither the provided baseline
nor any fetched text (the baseline says stdio unchanged) — MUST be caught by the
double-citation gate: no quotable spec clause → the finding is cut (or explicitly
tagged unverified-speculation and excluded from verdicts).
