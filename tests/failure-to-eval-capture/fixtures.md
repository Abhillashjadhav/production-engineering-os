# Gate 1 — Lint
`python3 tests/lint_skill.py .claude/skills/failure-to-eval-capture/SKILL.md` exits 0.

# Gate 2 — Trigger accuracy

SHOULD FIRE:
T1. "The summarizer invented an attendee yesterday — capture it as an eval case"
T2. "Turn this production failure into a permanent regression test"
T3. "Customer reported a wrong action-item assignment — encode it so it never ships again"
T4. "/pm this bad output made it to a customer — make it a test" (via orchestrator)
T5. "Add this incident to the golden set, scrubbed"

SHOULD NOT FIRE:
N1. "Build a golden set from these reviewed outputs"  (golden-dataset-builder — batch curation)
N2. "Why did the summarizer fail?"                    (root-cause investigation — research/eng)
N3. "Scrub PII from this document"                    (scrubbing alone, no eval encoding)
N4. "What's a regression test?"                        (knowledge question)

# Gate 3 — Known-answer

FIXTURE INPUT (production failure):
"Meeting summary failure, ticket #4521. Input meeting: 'Priya Sharma (priya@acmeco.com)
and Dr. Marco Ruiz discussed the Danske Bank integration. Marco agreed to draft the
API contract by March 3. Priya raised the Q2 budget overrun of $47,000.'
Bad output: 'Attendees: Priya, Marco, and Jens from Danske Bank. Jens will draft the
API contract.' — The summarizer INVENTED attendee 'Jens' from the company name and
reassigned Marco's action item to the invented person."

EXPECTED OUTPUT PROPERTIES:
1. THE SCRUB+PRESERVE GATE, both halves demonstrated:
   (a) PII scrubbed: real names, email, company, and distinctive figures replaced
   with stable placeholders (Person-A, person-a@company-x.example, Company-X/Bank-Y,
   [amount]) — a scrub table shown (original class → placeholder, NOT original
   values relisted; 'email address → person-a@…' not 'priya@acmeco.com → …').
   (b) Failure pattern demonstrably preserved: the case must still contain the
   TRIGGER STRUCTURE — an organization name mentioned as a topic (Bank-Y) with no
   person from that org present, plus an action item owned by a named attendee.
   The preservation check is explicit: 'the failure mechanism is entity-invention
   from org-name context; the scrubbed input retains org-as-topic + attendee-owned
   action item; a model with the same defect would still invent a Bank-Y person.'
   A scrub that also removes the trigger (e.g. deleting the bank entirely) = gate
   failure in the other direction — both over- and under-scrub are caught.
2. Eval-case encoding: id (F-4521) · scrubbed input · expected-behavior assertion
   (summary contains ONLY attendees present in input — mechanical check: every
   attendee name in output ∈ input attendee list) · failure class label
   (entity-invention) · provenance (date, ticket ref — not customer identity).
3. Regression wiring: the case joins the golden set's fail-class cases and the
   regression-gatekeeper run; the assertion is mechanical so no judge is needed.
4. Generalization, labeled: ONE optional variant case probing the same mechanism
   (different org-as-topic) explicitly labeled SYNTHETIC-VARIANT — never mixed in
   as if it were the real incident.
5. The original unscrubbed failure is never reproduced in the eval artifact.

PLANTED-FAILURE CASE:
A draft whose scrubbed input reads 'Person-A and Person-B discussed the integration.
Person-B agreed to draft the API contract by [date].' — PII clean, but the
org-as-topic trigger is gone: the case can no longer reproduce entity-invention,
so it tests nothing. The preserve half of the gate MUST catch this over-scrub and
restore a placeholder org (Bank-Y) as topic.
