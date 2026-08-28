# Reviewer personas — three-gate harness
Covers the 7 agents in `.claude/agents/`: engineer-reviewer, designer-reviewer,
executive-reviewer, skeptic-reviewer, customer-reviewer, data-analyst-reviewer,
legal-reviewer.

# Gate 1 — Manifest lint
`tests/lint_skill.py` targets SKILL.md files and does not apply to agents. Agent-file
gate: every `.claude/agents/*-reviewer.md` has YAML frontmatter that parses, with a
kebab-case `name` matching its filename and a `description` that states the "review
as X" trigger AND what the persona attacks. Check: `python3 -c "import yaml,glob,re,sys;
fails=[f for f in glob.glob('.claude/agents/*-reviewer.md') if not (lambda m: m and
(lambda d: d.get('name')==f.split('/')[-1][:-3] and 'review as' in d.get('description','').lower())
(yaml.safe_load(m.group(1))))(re.match(r'^---\n(.*?)\n---', open(f).read(), re.S))];
print(fails); sys.exit(1 if fails else 0)"` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE (each to exactly the named persona):
T1. "Review as engineer: [the GTM brief]"            → engineer-reviewer
T2. "Review this checklist as the skeptic"           → skeptic-reviewer
T3. "Run the announcement past legal"                → legal-reviewer
T4. "What would a customer say about this?"          → customer-reviewer
T5. "/pm review the retro as data-analyst"           → data-analyst-reviewer (via /pm routing)
T6. "Review as exec and as designer" (two personas, sequential, both gated)

SHOULD NOT FIRE:
N1. "Review this PR"                                  (/pr-review)
N2. "Pressure-test this strategy doc"                 (strategy-review — the skill, not a persona)
N3. "Review as a pirate"                              (no such persona — honest "7 personas exist: …" line, no improvised pirate)
N4. "What does an engineer reviewer do?"              (knowledge question)

# Gate 3 — Known-answer

FIXTURE ARTIFACT (numbered, a draft GTM brief excerpt):
L1. Audience: 10-50 seat agencies with 41 recap requests YTD.
L2. Positioning: the only scheduling tool with truly intelligent summaries.
L3. Channel: our 4-person sales team reaches all 2,000 workspaces this quarter.
L4. Success: attach 15% in 90 days; baseline none — pre-launch.
L5. The AI never misses an action item.

EXPECTED OBJECTION PROPERTIES (all personas, the shared binary gate):
1. EVERY objection cites the specific line/element it attacks (L1–L5) or is labeled
   GAP (something missing, no line to cite). Free-floating criticism = gate failure —
   same rule as strategy-review.
2. Each objection: [severity] line-cite → what breaks through THIS persona's lens →
   the question or fix. Lens purity: the engineer objects to feasibility (L3: 4
   people × 2,000 workspaces in a quarter — capacity math), not to tone.
3. Expected representative catches (any persona review must find its lens's target):
   - engineer → L3 capacity arithmetic; L5 as an unbuildable guarantee
   - skeptic → L2 unfalsifiable "only/truly intelligent"; L5 absolute claim
   - legal → L5 "never misses" (liability-shaped promise); L2 "only" (comparative
     advertising claim needing substantiation)
   - customer → L2 says nothing about what I get; trust cost of L5 when it misses one
   - data-analyst → L4 no denominator/cohort definition for "attach 15%"
   - executive → L3 sales-capacity vs. self-serve economics
   - designer → GAP: nothing in L1-L5 describes the first-run experience (labeled GAP, not a line attack)
4. A persona finding nothing through its lens says "clean through this lens" — no
   manufactured objections.
5. Personas review; they never rewrite the artifact. Output is objections only.

PLANTED-FAILURE CASE:
A persona draft containing "the brief feels salesy and unconvincing overall" — no
line cite, no lens mechanism — MUST be caught by the citation gate and either
concretized (e.g. skeptic → L2 unfalsifiable superlative) or cut. Same planted
failure as strategy-review's, applied at the persona layer.
