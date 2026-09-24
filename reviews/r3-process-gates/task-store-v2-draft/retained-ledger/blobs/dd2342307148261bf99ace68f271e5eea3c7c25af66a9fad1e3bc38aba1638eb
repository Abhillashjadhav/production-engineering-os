const state = {
  answers: {},
  history: [],
  question: null,
  approvalCard: null,
  approvedDigest: null,
};

const el = (id) => document.getElementById(id);
const status = (message) => { el("status").textContent = message; };

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "The request was blocked.");
  return body;
}

function showQuestion(result) {
  state.question = result.question;
  el("question-label").textContent = result.question.label;
  el("question-prompt").textContent = result.question.prompt;
  el("question-reason").textContent = result.question.reason;
  el("answer").placeholder = result.question.placeholder;
  el("answer").value = state.answers[result.question.field] || "";
  el("progress").max = result.total;
  el("progress").value = result.answered;
  el("progress-label").textContent = `${result.answered} of ${result.total} answered`;
  el("back").disabled = state.history.length === 0;
  el("question-view").classList.remove("hidden");
  el("review-view").classList.add("hidden");
  el("answer").focus();
  status(result.question.prompt);
}

function list(items) {
  return `<ul>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

function escapeHtml(value) {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[character]));
}

function showReview(result) {
  state.approvalCard = result.approval_card;
  const card = state.approvalCard;
  el("question-view").classList.add("hidden");
  el("review-view").classList.remove("hidden");
  el("approval-action").textContent = card.approval_action;
  el("approval-digest").textContent = card.digest;
  el("impact").innerHTML = `<p><strong>${escapeHtml(card.impact.level)}</strong> · ${escapeHtml(card.impact.summary)}</p><p>${card.impact.affected_requirements} requirements</p>`;
  el("reversibility").innerHTML = `<p><strong>${escapeHtml(card.reversibility.level)}</strong> · ${escapeHtml(card.reversibility.summary)}</p>`;
  el("evidence").innerHTML = `<p>${card.evidence.acceptance_criteria} acceptance criteria · ${card.evidence.golden_cases} golden cases · ${card.evidence.release_gates} release gates</p>`;
  el("cost").innerHTML = `<p><strong>External cost: ${escapeHtml(card.cost.estimated_external_cost)}</strong></p><p>${escapeHtml(card.cost.note)}</p>`;
  el("validity").textContent = card.validity.policy;
  el("permissions").innerHTML = `<p><strong>Allowed</strong></p>${list(card.permissions.allowed)}<p><strong>Not allowed</strong></p>${list(card.permissions.not_allowed)}`;
  el("exact-draft").textContent = JSON.stringify(result.draft, null, 2);
  el("review-title").focus?.();
  status("Draft ready for exact digest approval.");
}

async function loadNext() {
  try {
    const result = await api("/api/guided/review", { answers: state.answers });
    if (result.status === "DRAFT_READY_FOR_APPROVAL") showReview(result);
    else showQuestion(result);
  } catch (error) {
    status(error.message);
    window.alert(error.message);
  }
}

el("question-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const answer = el("answer").value.trim();
  if (!answer) return;
  if (!state.history.includes(state.question.field)) state.history.push(state.question.field);
  state.answers[state.question.field] = answer;
  await loadNext();
});

el("back").addEventListener("click", () => {
  const previous = state.history.pop();
  if (!previous) return;
  const question = state.question;
  state.question = { ...question, field: previous, label: previous.replaceAll("_", " ") };
  el("question-label").textContent = state.question.label;
  el("question-prompt").textContent = "Review or change your earlier answer";
  el("question-reason").textContent = "Changing product truth will produce a new review digest.";
  el("answer").value = state.answers[previous] || "";
  el("back").disabled = state.history.length === 0;
  el("answer").focus();
});

el("edit-answers").addEventListener("click", () => {
  const field = state.history.pop() || "product_name";
  state.question = { field, label: field.replaceAll("_", " ") };
  el("question-view").classList.remove("hidden");
  el("review-view").classList.add("hidden");
  el("question-label").textContent = state.question.label;
  el("question-prompt").textContent = "Review or change this answer";
  el("question-reason").textContent = "The approval digest will be recalculated.";
  el("answer").value = state.answers[field] || "";
  el("answer").focus();
});

el("approval-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/guided/approve", {
      approver: el("approver").value,
      confirmed_exact_digest: el("digest-confirmation").checked,
      expected_digest: state.approvalCard.digest,
    });
    state.approvedDigest = result.approved_contract_digest;
    el("review-view").classList.add("hidden");
    el("approved-view").classList.remove("hidden");
    el("approved-summary").textContent = `${result.contract_id} version ${result.contract_version} is approved. ${result.next_action}`;
    el("approved-title").focus();
    status("Contract approved locally.");
  } catch (error) {
    status(error.message);
    window.alert(error.message);
  }
});

el("pcr-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/guided/change-request", {
      approved_contract_digest: state.approvedDigest,
      engineering_finding: el("pcr-finding").value,
      reason: el("pcr-reason").value,
      options: el("pcr-options").value,
      engineering_consequences: el("pcr-consequences").value,
      recommended_technical_default: el("pcr-default").value,
      decision_owner: el("pcr-owner").value,
    });
    event.target.reset();
    status(`Change request ${result.change_request.request_id} created.`);
    window.alert(`Created ${result.change_request.request_id}. The approved contract was not changed.`);
  } catch (error) {
    status(error.message);
    window.alert(error.message);
  }
});

el("intake-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const [bundleFile] = el("bundle-file").files;
  const [manifestFile] = el("manifest-file").files;
  try {
    const result = await api("/api/bundles/intake", {
      bundle_text: await bundleFile.text(),
      manifest_text: await manifestFile.text(),
    });
    el("intake-result").innerHTML = `<h3>${escapeHtml(result.status)}</h3><pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
    status(`Canonical intake ${result.status.toLowerCase()}.`);
  } catch (error) {
    status(error.message);
    window.alert(error.message);
  }
});

const tabs = [...document.querySelectorAll('[role="tab"]')];
async function loadCatalog() {
  try {
    const response = await fetch("/api/workflows/catalog");
    if (!response.ok) throw new Error("Workflow catalogue could not be loaded.");
    const body = await response.json();
    el("catalog-list").innerHTML = body.workflows.map((item) => `
      <article>
        <p class="eyebrow">Tier ${item.tier}</p>
        <h3>${escapeHtml(item.workflow_id.replaceAll("-", " "))}</h3>
        <p>${escapeHtml(item.problem_solved)}</p>
        <p><strong>Output:</strong> ${escapeHtml(item.output_name)}</p>
        <p><strong>Approval:</strong> ${escapeHtml(item.approvals.join(", "))}</p>
        <details><summary>Controls</summary>${list(item.done)}<p>${escapeHtml(item.budget)}</p></details>
      </article>
    `).join("");
  } catch (error) {
    el("catalog-list").textContent = error.message;
  }
}
function activateTab(tab) {
  tabs.forEach((item) => {
    item.setAttribute("aria-selected", "false");
    item.setAttribute("tabindex", "-1");
  });
  document.querySelectorAll('[role="tabpanel"]').forEach((panel) => panel.classList.add("hidden"));
  tab.setAttribute("aria-selected", "true");
  tab.setAttribute("tabindex", "0");
  el(tab.getAttribute("aria-controls")).classList.remove("hidden");
  if (tab.id === "catalog-tab") loadCatalog();
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => {
    activateTab(tab);
  });
  tab.addEventListener("keydown", (event) => {
    let target = index;
    if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") target = 0;
    else if (event.key === "End") target = tabs.length - 1;
    else return;
    event.preventDefault();
    activateTab(tabs[target]);
    tabs[target].focus();
  });
});

loadNext();
