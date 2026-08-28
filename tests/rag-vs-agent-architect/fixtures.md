# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/rag-vs-agent-architect/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "Should our docs assistant be RAG or an agent?"
T2. "Architecture call: RAG, tool-calling, full agent, or hybrid for this workflow?"
T3. "Do we need an agent here or is retrieval enough?"
T4. "/pm design the AI architecture for the expense-approval assistant" (via orchestrator)
T5. "Everyone wants to build an agent — is that right for our search use case?"

SHOULD NOT FIRE:
N1. "Which vector DB should we use?"             (component selection inside a chosen architecture)
N2. "Go/no-go on the assistant feature"          (ai-feature-go-no-go)
N3. "What is RAG?"                               (knowledge question)
N4. "Build vs buy the RAG pipeline"              (build-buy-partner)

# Gate 3 — Known-answer

FIXTURE INPUT:
"Problem: employees ask HR-policy questions in Slack ('how many vacation days do I
carry over?'). Answers live in 40 policy PDFs, updated quarterly. Wrong answers are
bad but survivable (HR reviews contested cases). No actions need to be taken —
answer-only. Volume ~200 questions/week. Latency: chat-acceptable (<10s)."

EXPECTED OUTPUT PROPERTIES:
1. A recommendation from {RAG, tool-calling, agent, hybrid} with the match to stated
   problem properties (static corpus, answer-only, no actions, moderate stakes).
   Expected shape for this fixture: RAG (retrieval over indexed PDFs) — but the gate
   checks process: a defensible alternative passes if properties 2-4 hold.
2. THE REJECTED-FAILURE-MODES GATE: for EVERY rejected architecture, the output states
   the failure mode of using it HERE — not generic cons:
   - agent rejected → e.g. "multi-step planning adds latency+cost+failure surface to
     a single-hop lookup; agent loops can act, and this problem forbids actions"
   - tool-calling rejected → what breaks or what it wastes for this shape
   - hybrid rejected → the added complexity buys nothing at 200 q/week
   A recommendation praising the chosen architecture with no rejected-option failure
   modes = gate failure.
3. The chosen architecture ALSO carries its own failure mode + mitigation (RAG →
   stale index after quarterly updates → reindex trigger; retrieval miss → cite-or-
   escalate rule). A choice presented as failure-free = gate failure.
4. Requirements the answer turns on are quoted from input (no actions, 200/wk, <10s);
   no invented constraints (compliance rules, budgets not stated).
5. A revisit trigger: what change flips the architecture (e.g. "if the assistant must
   FILE the carry-over request, the no-actions property is gone — re-run this call").

PLANTED-FAILURE CASE:
A draft recommending "agent, because agents are the most capable and future-proof
approach" — benefits-only, no failure modes for rejected options, no match to stated
properties — MUST be caught by the gate and rebuilt from the problem shape.
