const state = {
  exampleId: "fl-v04",
  report: null,
  rankerVersion: null,
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", async () => {
  if (window.lucide) window.lucide.createIcons();
  bindNavigation();
  bindActions();
  await checkHealth();
  await loadExample(state.exampleId);
  await loadStrategies();
  await loadRankers();
});

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".workspace").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(button.dataset.section).classList.add("active");
    });
  });
}

function bindActions() {
  $("exampleSelect").addEventListener("change", (event) => loadExample(event.target.value));
  $("resetButton").addEventListener("click", () => loadExample(state.exampleId));
  $("generateButton").addEventListener("click", generatePlan);
  $("downloadButton").addEventListener("click", downloadPlan);
}

async function checkHealth() {
  try {
    const response = await fetch("/healthz");
    if (!response.ok) throw new Error("unavailable");
    $("apiState").innerHTML = '<span class="status-dot"></span><span>API ready</span>';
  } catch (_) {
    $("apiState").innerHTML = '<span class="status-dot" style="background:#a13a3a"></span><span>API unavailable</span>';
  }
}

async function loadExample(exampleId) {
  state.exampleId = exampleId;
  $("exampleSelect").value = exampleId;
  const response = await fetch(`/api/examples/${exampleId}`);
  const data = await response.json();
  $("requestJson").value = JSON.stringify(data.input, null, 2);
  $("contextJson").value = JSON.stringify(data.context || {}, null, 2);
  renderInputSummary(data.input, data.context || {});
  resetDecision();
}

function renderInputSummary(input, context) {
  const mode = input.learning_mode?.selected || input.inference_mode?.selected || "native";
  $("taskType").textContent = input.task_type || "partition request";
  $("selectedMode").textContent = mode;
  $("participantCount").textContent = String(input.candidate_participants?.length || 0);
  $("modelReference").textContent = input.model_ref ? `${input.model_ref.model_id}:${input.model_ref.version}` : "from request";
  $("contextSource").textContent = context.participant_context?.source || "Native system context";
}

async function generatePlan() {
  const button = $("generateButton");
  const status = $("planStatus");
  button.disabled = true;
  status.className = "state-badge running";
  status.textContent = "Planning";
  $("emptyState").classList.remove("hidden");
  $("emptyState").querySelector("strong").textContent = "Candidate plans are being evaluated";
  $("emptyState").querySelector("span").textContent = "Context resolution, feasibility checks, and deterministic selection are in progress.";
  animateProcessing();
  try {
    const request = JSON.parse($("requestJson").value);
    const context = JSON.parse($("contextJson").value || "{}");
    const endpoint = state.exampleId.endsWith("v04") ? "/api/coordination-plans" : "/api/plans";
    const payload = endpoint.includes("coordination")
      ? { coordination_plan: request, context, selection_mode: $("selectionMode").value, ranker_model_version: state.rankerVersion }
      : { request, selection_mode: $("selectionMode").value, ranker_model_version: state.rankerVersion };
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const report = await response.json();
    if (!response.ok) throw new Error(report.detail?.message || report.detail || "Planning failed");
    state.report = report;
    renderReport(report);
  } catch (error) {
    status.className = "state-badge blocked";
    status.textContent = "Blocked";
    $("emptyState").querySelector("strong").textContent = "Plan generation was blocked";
    $("emptyState").querySelector("span").textContent = String(error.message || error);
    renderHandoff(null, true);
  } finally {
    button.disabled = false;
  }
}

function animateProcessing() {
  const steps = [...document.querySelectorAll(".process-step")];
  steps.forEach((step) => step.classList.remove("done", "running"));
  steps.forEach((step, index) => {
    window.setTimeout(() => {
      steps.slice(0, index).forEach((done) => done.classList.add("done"));
      step.classList.add("running");
    }, index * 120);
  });
}

function renderReport(report) {
  document.querySelectorAll(".process-step").forEach((step) => {
    step.classList.remove("running");
    step.classList.add("done");
  });
  $("emptyState").classList.add("hidden");
  $("decisionContent").classList.remove("hidden");
  const plan = report.plan;
  const candidate = plan.selected_candidate;
  const evaluation = report.evaluation;
  $("planStatus").className = `state-badge ${report.status === "planned" ? "ready" : "blocked"}`;
  $("planStatus").textContent = report.status === "planned" ? "Plan ready" : "Blocked";
  $("planType").textContent = plan.plan_type || "legacy";
  $("strategyId").textContent = plan.strategy_id || "legacy-policy";
  $("executionMode").textContent = plan.approved_execution_mode;
  $("confidence").textContent = Number(plan.confidence || 0).toFixed(2);
  $("partitionCount").textContent = `${candidate.partitions.length} partitions`;
  $("partitionLanes").innerHTML = candidate.partitions.map((partition) => `
    <div class="partition-lane">
      <strong>${escapeHtml(partition.partition_id)}</strong>
      <span>${escapeHtml(partition.layer_names.join(" → "))}</span>
      <code>${escapeHtml(partition.device_id)}</code>
    </div>
  `).join("");
  $("latencyMetric").textContent = `${Number(candidate.estimated_total_latency_ms).toFixed(2)} ms`;
  $("memoryMetric").textContent = `${(Number(candidate.maximum_memory_pressure) * 100).toFixed(1)}%`;
  $("transferMetric").textContent = formatBytes(candidate.total_transfer_bytes);
  $("rewardMetric").textContent = Number(evaluation.reward).toFixed(3);
  $("rawPlan").textContent = JSON.stringify(report, null, 2);
  renderHandoff(report, report.status !== "planned");
}

function renderHandoff(report, blocked) {
  const box = $("handoffStatus");
  if (!report) {
    box.className = "handoff-status blocked";
    box.innerHTML = '<span class="status-dot" style="background:#a13a3a"></span><strong>Blocked</strong>';
    return;
  }
  const plan = report.plan;
  box.className = `handoff-status ${blocked ? "blocked" : "ready"}`;
  box.innerHTML = `<span class="status-dot"></span><strong>${blocked ? "Human review required" : "Ready for external scheduler"}</strong>`;
  $("planId").textContent = plan.plan_id;
  $("planVersion").textContent = String(plan.plan_version);
  $("validationState").textContent = report.validation.valid ? "passed" : "failed";
  $("humanReview").textContent = plan.human_review_required ? "required" : "not required";
  $("schedulerRef").textContent = report.scheduling_handoff?.scheduler_ref || "External";
  $("downloadButton").disabled = false;
}

function resetDecision() {
  state.report = null;
  $("planStatus").className = "state-badge idle";
  $("planStatus").textContent = "Waiting";
  $("decisionContent").classList.add("hidden");
  $("emptyState").classList.remove("hidden");
  $("emptyState").querySelector("strong").textContent = "Planning input is ready";
  $("emptyState").querySelector("span").textContent = "Generate a plan to inspect partition placement and execution graph.";
  document.querySelectorAll(".process-step").forEach((step) => step.classList.remove("done", "running"));
  $("handoffStatus").className = "handoff-status idle";
  $("handoffStatus").innerHTML = '<span class="status-dot"></span><strong>Not generated</strong>';
  ["planId", "planVersion", "validationState", "humanReview"].forEach((id) => $(id).textContent = "-");
  $("schedulerRef").textContent = "External";
  $("downloadButton").disabled = true;
}

async function loadStrategies() {
  const response = await fetch("/api/strategies");
  const data = await response.json();
  $("strategyCatalog").innerHTML = data.strategies.map((strategy) => `
    <div class="strategy-row">
      <strong>${escapeHtml(strategy.strategy_id)}</strong>
      <span>${escapeHtml(strategy.supported_modes.join(", "))}</span>
      <code>${escapeHtml(strategy.strategy_version)}</code>
    </div>
  `).join("");
}

async function loadRankers() {
  const response = await fetch("/api/rankers");
  const data = await response.json();
  const versions = data.rankers.map((ranker) => ranker.model_version);
  state.rankerVersion = versions[0] || null;
  const select = $("selectionMode");
  [...select.options].forEach((option) => {
    if (option.value !== "deterministic") option.disabled = versions.length === 0;
  });
  select.title = versions.length === 0
    ? "Register a validated ranker artifact before enabling learned selection."
    : `Registered ranker: ${state.rankerVersion}`;
}

function downloadPlan() {
  if (!state.report) return;
  const blob = new Blob([JSON.stringify(state.report, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.report.plan.plan_id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(2)} MiB`;
  return `${bytes} B`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}
