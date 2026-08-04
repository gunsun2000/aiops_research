(function () {
  "use strict";

  const REGISTERED_SCENARIOS = {
    "cpu-stress": { label: "CPU Stress", namespace: "online-boutique", deployment: "paymentservice", metric: "cpu", threshold: 80 },
    "memory-stress": { label: "Memory Stress", namespace: "online-boutique", deployment: "checkoutservice", metric: "memory", threshold: 80 },
    "network-delay": { label: "Network Delay", namespace: "online-boutique", deployment: "paymentservice", metric: "latency", threshold: 0.1 },
    "pod-kill": { label: "Pod Kill", namespace: "online-boutique", deployment: "paymentservice", metric: "availability", threshold: 1 },
    "aiopslab-hotel-reservation": {
      label: "AIOpsLab Hotel Detection",
      namespace: "test-hotel-reservation",
      deployment: "geo",
      metric: "availability",
      threshold: 1,
      incident_source: "aiopslab",
      benchmark_id: "hotel-reservation-detection-v1",
    },
  };

  const AGENTS = {
    AIServiceHASupportAgent: { code: "HA", pending: "가용성 진단 대기" },
    AIApplicationManagementAgent: { code: "APP", pending: "복구 제안 대기" },
    AISemiconductorInfraOpsAgent: { code: "INF", pending: "자원 검토 대기" },
    CostOptimizationAgent: { code: "CST", pending: "비용 검토 대기" },
  };

  const MODE_BOUNDARIES = {
    mock: "Mock은 합성 Evidence를 사용하며 Kubernetes를 변경하지 않습니다.",
    "dry-run": "Dry-run은 실제 대상에 대한 명령 검증을 수행하지만 Kubernetes 상태를 변경하지 않습니다.",
    real: "Real은 CONFIRM_REAL_RUN 환경 Gate와 확인 문구가 모두 통과한 경우에만 실제 Kubernetes를 제어합니다.",
  };

  const COMPARISON_BOUNDARY_NOTE = "Mock 비교는 합성 데이터이며 Ubuntu Real 비교만 실제 클러스터 연구 근거입니다.";

  const RESEARCH_DOCUMENTS = [
    {
      label: "4-Agent 연구 보고서",
      text: "DOCX",
      sourcePath: "docs/deliverables/AIOps_4Agent_Research_Report.docx",
    },
    {
      label: "실험 실행 가이드",
      text: "DOCX",
      sourcePath: "docs/deliverables/AIOps_Experiment_Operations_Guide.docx",
    },
    {
      label: "Agent 정책 명세",
      text: "DOCX",
      sourcePath: "docs/deliverables/AIOps_Agent_Policy_Specification.docx",
    },
  ];

  const WORKFLOW_PHASES = [
    ["preflight", "injecting_fault", "collecting_evidence"],
    ["agent_reasoning"],
    ["validating"],
    ["executing", "observing_recovery", "cleanup", "completed"],
  ];

  const PLATFORM_VIEWS = new Set([
    "overview",
    "experiment",
    "agents",
    "observability",
    "analysis",
    "history",
  ]);
  const PRIMARY_VIEW_BY_PANEL = {
    overview: "overview",
    experiment: "experiment",
    agents: "experiment",
    observability: "experiment",
    analysis: "analysis",
    history: "analysis",
  };

  const TERMINAL = new Set(["completed", "failed", "blocked", "cancelled", "interrupted"]);
  const state = {
    activeView: "overview",
    scenarios: { ...REGISTERED_SCENARIOS },
    selectedScenario: "cpu-stress",
    selectedMode: "mock",
    selectedAgent: "AIServiceHASupportAgent",
    experimentId: "",
    job: null,
    events: [],
    eventSource: null,
    startedAt: null,
    timer: null,
    running: false,
    connections: {},
    comparisonRuntime: {},
    comparisonJobId: "",
    comparisonJob: null,
    comparisonEventSource: null,
    comparisonEvents: [],
  };

  const elements = Object.fromEntries([
    "connection-dot", "connection-label", "connection-summary", "experiment-id",
    "job-status", "current-stage", "consensus-status", "safety-status",
    "scenario-list", "mode-control", "controller-select", "controller-options",
    "autogen-controller-state", "profile-select", "controller-model",
    "model-input", "controller-readiness",
    "advanced-settings", "repetitions-select", "selection-summary",
    "target-deployment", "target-metric", "mode-boundary",
    "run-experiment", "cancel-experiment", "control-error", "elapsed-time",
    "stage-timeline", "evidence-scenario", "evidence-target", "evidence-metric",
    "evidence-source", "agent-grid", "review-summary", "consensus-summary",
    "action-summary", "event-count", "event-log", "agent-tabs", "selected-agent",
    "agent-decision", "agent-approval", "agent-reward", "agent-statement",
    "peer-reviews", "controller-provenance", "autogen-transcript-panel",
    "autogen-transcript", "allowlist-result", "validator-result", "cleanup-result",
    "result-status", "result-recovery", "result-mttr", "result-reward",
    "result-reviews", "result-artifacts", "research-documents", "autogen-summary",
    "aiopslab-summary",
    "recovery-comparison-panel", "comparison-runtime-status", "comparison-mode",
    "comparison-repetitions", "comparison-guard", "comparison-run",
    "comparison-cancel", "comparison-boundary", "comparison-job-status",
    "comparison-progress", "comparison-success-rate", "comparison-mean-recovery",
    "comparison-evidence", "comparison-success-chart", "comparison-recovery-chart",
    "comparison-event-count", "comparison-event-log", "comparison-artifacts",
    "comparison-error", "global-experiment-id", "global-scenario",
    "global-controller", "global-stage", "overview-job-status",
    "overview-consensus-status", "overview-safety-status",
    "overview-recovery-status", "observed-scenario", "observed-target",
    "observed-metric", "observed-provider",
  ].map((id) => [id, document.getElementById(id)]));

  async function api(path, options) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options && options.headers) },
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      throw new Error(payload && payload.detail ? payload.detail : `요청 실패 (${response.status})`);
    }
    return payload;
  }

  function scenario() {
    return state.scenarios[state.selectedScenario] || REGISTERED_SCENARIOS["cpu-stress"];
  }

  function normalizeScenario(item) {
    const id = item.scenario_id || item.id;
    const fallback = REGISTERED_SCENARIOS[id] || {};
    return {
      label: item.label || fallback.label || id,
      namespace: item.namespace || fallback.namespace,
      deployment: item.deployment || fallback.deployment,
      metric: item.metric || fallback.metric,
      threshold: item.threshold == null ? fallback.threshold : item.threshold,
      incident_source: item.incident_source || fallback.incident_source || "chaos_mesh",
      benchmark_id: item.benchmark_id || fallback.benchmark_id || "",
    };
  }

  function setPressed(container, selector, selected) {
    container.querySelectorAll(selector).forEach((button) => {
      const value = button.dataset.scenario || button.dataset.mode || button.dataset.controller || button.dataset.agent || button.dataset.agentTab;
      button.setAttribute("aria-pressed", String(value === selected));
    });
  }

  function selectPlatformView(viewName, updateHash = true) {
    const resolved = PLATFORM_VIEWS.has(viewName) ? viewName : "overview";
    state.activeView = resolved;
    const primaryView = PRIMARY_VIEW_BY_PANEL[resolved] || "overview";
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.view === primaryView));
    });
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
      const active = panel.dataset.viewPanel === resolved;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    if (updateHash && window.location.hash !== `#${resolved}`) {
      window.location.hash = resolved;
    }
  }

  function bindPlatformNavigation() {
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => selectPlatformView(button.dataset.view));
    });
    document.querySelectorAll("[data-view-link]").forEach((button) => {
      button.addEventListener("click", () => {
        const scenarioId = button.dataset.scenarioLink;
        if (scenarioId && state.scenarios[scenarioId]) selectScenario(scenarioId);
        selectPlatformView(button.dataset.viewLink);
      });
    });
    window.addEventListener("hashchange", () => {
      selectPlatformView(window.location.hash.slice(1), false);
    });
    selectPlatformView(window.location.hash.slice(1) || "overview", false);
  }

  function renderGlobalContext(job) {
    const request = job && job.request ? job.request : {};
    const scenarioId = request.scenario_id || state.selectedScenario;
    const scenarioItem = state.scenarios[scenarioId] || REGISTERED_SCENARIOS[scenarioId];
    const controller = request.controller || elements["controller-select"].value || "deterministic";
    const stage = job && job.current_stage ? job.current_stage : "queued";
    const experimentId = job && job.experiment_id ? job.experiment_id : "새 실험";

    elements["global-experiment-id"].textContent = experimentId;
    elements["global-experiment-id"].title = experimentId;
    elements["global-scenario"].textContent = scenarioItem ? scenarioItem.label : scenarioId;
    elements["global-controller"].textContent = controller === "autogen" ? "AutoGen GroupChat" : "Deterministic";
    elements["global-stage"].textContent = stage;
    elements["overview-job-status"].textContent = job ? jobStatusLabel(job.status) : "대기";
    elements["observed-scenario"].textContent = scenarioItem ? scenarioItem.label : scenarioId;
    elements["observed-target"].textContent = scenarioItem
      ? `${scenarioItem.namespace}/${scenarioItem.deployment}`
      : "—";
    elements["observed-metric"].textContent = scenarioItem
      ? `${scenarioItem.metric} · threshold ${scenarioItem.threshold}`
      : "—";
  }

  function renderScenarioButtons() {
    elements["scenario-list"].replaceChildren(...Object.entries(state.scenarios).map(([id, item]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.scenario = id;
      button.setAttribute("aria-pressed", String(id === state.selectedScenario));
      const title = document.createElement("strong");
      title.textContent = item.label;
      const metadata = document.createElement("span");
      metadata.textContent = item.incident_source === "aiopslab"
        ? `AIOpsLab · ${item.deployment}`
        : `Chaos Mesh · ${item.deployment} · ${item.metric}`;
      button.append(title, metadata);
      button.addEventListener("click", () => selectScenario(id));
      return button;
    }));
  }

  function selectScenario(id) {
    if (state.running || !state.scenarios[id]) return;
    state.selectedScenario = id;
    setPressed(elements["scenario-list"], "button", id);
    renderCondition();
    resetEvidenceView();
  }

  function selectMode(mode) {
    if (state.running) return;
    state.selectedMode = mode;
    setPressed(elements["mode-control"], "button", mode);
    elements["mode-boundary"].textContent = MODE_BOUNDARIES[mode];
    renderSelectionSummary();
    resetEvidenceView();
  }

  function controllerProfile() {
    return elements["controller-select"].value === "autogen"
      ? "four-agent-autogen-v1"
      : elements["profile-select"].value;
  }

  function selectController(controller) {
    if (state.running) return;
    const resolved = controller === "autogen" ? "autogen" : "deterministic";
    const autogen = state.connections.autogen || { ready: false, reason: "AutoGen 연결 정보 없음" };
    const isAutogen = resolved === "autogen";
    elements["controller-select"].value = resolved;
    setPressed(elements["controller-options"], "button[data-controller]", resolved);
    elements["controller-model"].hidden = !isAutogen;
    elements["advanced-settings"].open = isAutogen;
    elements["profile-select"].disabled = isAutogen;
    elements["profile-select"].value = isAutogen
      ? "four-agent-autogen-v1"
      : "four-agent-role-veto-v1";
    elements["controller-readiness"].textContent = isAutogen
      ? (autogen.reason || "AutoGen runtime 준비")
      : "Deterministic 4-Agent runtime";
    elements["run-experiment"].disabled = state.running || (isAutogen && !autogen.ready);
    elements["control-error"].textContent = isAutogen && !autogen.ready
      ? (autogen.reason || "AutoGen runtime is not ready")
      : "";
    renderSelectionSummary();
  }

  function selectAgent(agent) {
    state.selectedAgent = agent;
    setPressed(elements["agent-grid"], "button", agent);
    setPressed(elements["agent-tabs"], "button", agent);
    renderInspector();
  }

  function renderCondition() {
    const item = scenario();
    elements["target-deployment"].textContent = `${item.namespace} / ${item.deployment}`;
    elements["target-metric"].textContent = `${item.metric} · threshold ${item.threshold}`;
    elements["evidence-scenario"].textContent = item.label;
    elements["evidence-target"].textContent = `${item.namespace}/${item.deployment}`;
    renderSelectionSummary();
    renderGlobalContext(null);
  }

  function renderSelectionSummary() {
    const item = scenario();
    const mode = ({ mock: "Mock", "dry-run": "Dry-run", real: "Real" })[state.selectedMode] || state.selectedMode;
    const controller = elements["controller-select"].value === "autogen" ? "AutoGen" : "Deterministic";
    elements["selection-summary"].textContent = `${item.label} · ${mode} · ${controller}`;
  }

  function resetEvidenceView() {
    elements["evidence-metric"].textContent = "실험 Evidence 수집 후 표시";
    const item = scenario();
    elements["evidence-source"].textContent = item.incident_source === "aiopslab"
      ? (state.selectedMode === "real" ? "AIOpsLab + Prometheus + Kubernetes" : "AIOpsLab synthetic evidence")
      : (state.selectedMode === "real" ? "Chaos Mesh + Prometheus + Kubernetes" : "FakeEvidenceProvider");
    elements["review-summary"].textContent = "역할별 의견 수집 대기";
    elements["consensus-summary"].textContent = "대기";
    elements["action-summary"].textContent = "선택 전";
    elements["consensus-status"].textContent = "Evidence 대기";
    elements["safety-status"].textContent = "검증 대기";
    renderAgentCards(null);
    renderInspector();
  }

  function runtimeReport() {
    const attempts = state.job && state.job.result && state.job.result.attempts;
    if (!Array.isArray(attempts) || attempts.length === 0) return null;
    return attempts[attempts.length - 1].report || null;
  }

  function runtimeDetection() {
    const attempts = state.job && state.job.result && state.job.result.attempts;
    if (!Array.isArray(attempts) || attempts.length === 0) return null;
    const attempt = attempts[attempts.length - 1];
    return attempt.detection || (attempt.report && attempt.report.detection) || null;
  }

  function initialDecision(agent, report) {
    if (!report || !Array.isArray(report.initial_decisions)) return null;
    return report.initial_decisions.find((item) => item.agent === agent) || null;
  }

  function reviewsBy(agent, report) {
    if (!report || !Array.isArray(report.peer_reviews)) return [];
    return report.peer_reviews.filter((item) => item.reviewer === agent);
  }

  function contribution(agent, report) {
    return report && report.agent_contributions ? report.agent_contributions[agent] || {} : {};
  }

  function renderAgentCards(report) {
    elements["agent-grid"].querySelectorAll("button[data-agent]").forEach((button) => {
      const agent = button.dataset.agent;
      const decision = initialDecision(agent, report);
      const reviews = reviewsBy(agent, report);
      const status = button.querySelector("small");
      if (decision) {
        status.textContent = decision.proposed_action ? actionLabel(decision.proposed_action) : decision.reason;
      } else if (reviews.length) {
        status.textContent = `${reviews.length}개 검토 · ${reviews[0].verdict}`;
      } else {
        status.textContent = AGENTS[agent].pending;
      }
    });
  }

  function renderInspector() {
    const report = runtimeReport();
    const decision = initialDecision(state.selectedAgent, report);
    const reviews = reviewsBy(state.selectedAgent, report);
    const stats = contribution(state.selectedAgent, report);
    elements["selected-agent"].textContent = state.selectedAgent;
    elements["agent-decision"].textContent = decision ? (decision.decision_type || "판단 완료") : (reviews.length ? "Peer review" : "실험 Evidence 수집 후 표시");
    elements["agent-approval"].textContent = decision ? (decision.approved ? "승인" : "거부") : (reviews.length ? reviews[0].verdict : "대기");
    const reward = decision && decision.reward != null ? decision.reward : stats.reward;
    elements["agent-reward"].textContent = reward == null ? "—" : Number(reward).toFixed(3);
    elements["controller-provenance"].textContent = report
      ? `${report.controller || "deterministic"}${report.model ? ` · ${report.model}` : ""}`
      : "deterministic";
    elements["agent-statement"].textContent = decision ? decision.reason : (reviews[0] ? reviews[0].reason : "실제 실행 결과의 Agent 판단 근거만 표시합니다.");
    elements["peer-reviews"].replaceChildren(...(reviews.length ? reviews : [{ reason: "상호검토 기록 대기", verdict: "" }]).map((review) => {
      const item = document.createElement("li");
      item.textContent = `${review.verdict ? `[${review.verdict}] ` : ""}${review.reason}`;
      return item;
    }));
    renderAutoGenTranscript(report);
  }

  function renderAutoGenTranscript(report) {
    const isAutogen = report && report.controller === "autogen";
    elements["autogen-transcript-panel"].hidden = !isAutogen;
    if (!isAutogen) return;
    const lines = Array.isArray(report.autogen_transcript)
      ? report.autogen_transcript
      : [];
    elements["autogen-transcript"].replaceChildren(...(lines.length ? lines : ["AutoGen transcript가 기록되지 않았습니다."]).map((line) => {
      const item = document.createElement("li");
      item.textContent = line;
      return item;
    }));
  }

  function actionLabel(action) {
    if (!action || !action.kind) return "선택 전";
    return action.replicas == null ? action.kind : `${action.kind} → ${action.replicas}`;
  }

  function renderJob(job) {
    state.job = job;
    state.experimentId = job.experiment_id;
    state.running = !TERMINAL.has(job.status);
    if (job.request) {
      if (state.scenarios[job.request.scenario_id]) {
        state.selectedScenario = job.request.scenario_id;
        setPressed(elements["scenario-list"], "button", state.selectedScenario);
        renderCondition();
      }
      elements["controller-select"].value = job.request.controller || "deterministic";
      setPressed(elements["controller-options"], "button[data-controller]", elements["controller-select"].value);
      elements["model-input"].value = job.request.model || elements["model-input"].value;
      elements["profile-select"].value = job.request.protocol_profile || "four-agent-role-veto-v1";
      elements["controller-model"].hidden = job.request.controller !== "autogen";
      elements["advanced-settings"].open = job.request.controller === "autogen";
      elements["profile-select"].disabled = job.request.controller === "autogen";
    }
    renderSelectionSummary();
    elements["experiment-id"].textContent = job.experiment_id;
    elements["job-status"].textContent = jobStatusLabel(job.status);
    elements["current-stage"].textContent = job.current_stage;
    renderGlobalContext(job);
    const unavailableAutogen = elements["controller-select"].value === "autogen"
      && !(state.connections.autogen && state.connections.autogen.ready);
    elements["run-experiment"].disabled = state.running || unavailableAutogen;
    elements["cancel-experiment"].disabled = !state.running;
    const report = runtimeReport();
    renderAgentCards(report);
    renderInspector();
    renderReport(report);
    updateStage(job.current_stage, TERMINAL.has(job.status) && job.status !== "completed");
    if (TERMINAL.has(job.status)) stopTimer();
  }

  function renderReport(report) {
    if (!report) return;
    const evidence = report.evidence || {};
    const detection = runtimeDetection();
    const metrics = evidence.metric_values || {};
    const metricEntries = Object.entries(metrics);
    elements["evidence-metric"].textContent = detection && detection.source === "aiopslab"
      ? `Accuracy ${formatAccuracy(detection.accuracy)} · TTD ${formatSeconds(detection.ttd_seconds)} · ${formatValue(detection.steps)} steps`
      : (metricEntries.length ? metricEntries.map(([key, value]) => `${key} ${formatValue(value)}`).join(" · ") : "수집 결과 없음");
    const evidenceSource = detection && detection.source === "aiopslab"
      ? `AIOpsLab · ${detection.evidence_boundary || evidence.source || "evidence"}`
      : (evidence.source || "unknown");
    elements["evidence-source"].textContent = evidenceSource;
    elements["observed-provider"].textContent = evidenceSource;
    const reviews = Array.isArray(report.peer_reviews) ? report.peer_reviews : [];
    elements["review-summary"].textContent = `${reviews.length}개 역할별 검토`;
    const negotiation = report.negotiation || {};
    elements["consensus-summary"].textContent = negotiation.consensus || "미합의";
    elements["consensus-status"].textContent = negotiation.consensus === "approved" ? "합의 완료" : "합의 확인 필요";
    elements["overview-consensus-status"].textContent = negotiation.consensus || "대기";
    elements["action-summary"].textContent = actionLabel(report.selected_action);
    const safety = report.safety_validation || {};
    elements["allowlist-result"].textContent = safety.valid === true ? "통과" : "차단/대기";
    elements["validator-result"].textContent = safety.valid === true ? "VALID" : "대기";
    elements["safety-status"].textContent = report.final_status === "safe_failure"
      ? "명령 검증 통과 · 사후검토 중단"
      : (safety.valid === true ? "안전 검증 통과" : "검증 미완료");
    elements["overview-safety-status"].textContent = report.final_status === "safe_failure"
      ? "POST-REVIEW BLOCKED"
      : (safety.valid === true ? "VALID" : "검증 대기");
    const cleanup = report.cleanup || {};
    elements["cleanup-result"].textContent = cleanup.valid === false ? "실패 · 검토 필요" : "완료/불필요";
    const recovery = report.recovery_monitoring || {};
    elements["result-status"].textContent = report.final_status || "완료";
    elements["result-recovery"].textContent = report.final_status === "safe_failure"
      ? "안전 중단"
      : (recovery.recovery_success === true ? "성공" : (recovery.recovery_success === false ? "실패" : "—"));
    elements["overview-recovery-status"].textContent = elements["result-recovery"].textContent;
    elements["result-mttr"].textContent = recovery.recovery_seconds == null ? "—" : `${recovery.recovery_seconds}s`;
    const contributions = Object.values(report.agent_contributions || {});
    const reward = contributions.reduce((sum, item) => sum + Number(item.reward || 0), 0);
    elements["result-reward"].textContent = contributions.length ? reward.toFixed(3) : "—";
    elements["result-reviews"].textContent = String(reviews.length);
    const artifacts = Object.keys(report.artifacts || {});
    elements["result-artifacts"].textContent = detection && detection.report_path
      ? "AIOpsLab report + Job DB"
      : (artifacts.length ? `${artifacts.length}개` : "Job DB 저장");
  }

  function formatValue(value) {
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
    return String(value);
  }

  function formatAccuracy(value) {
    if (value == null) return "-";
    if (Number.isNaN(Number(value))) return String(value);
    return `${(Number(value) * 100).toFixed(1)}%`;
  }

  function formatSeconds(value) {
    if (value == null || Number.isNaN(Number(value))) return "-";
    return `${Number(value).toFixed(3)}s`;
  }

  function jobStatusLabel(status) {
    return ({ queued: "대기", running: "실행 중", cancelling: "취소 중", completed: "완료", failed: "실패", blocked: "안전 차단", cancelled: "취소됨", interrupted: "서버 재시작으로 중단" })[status] || status;
  }

  function updateStage(stage, failed) {
    let index = WORKFLOW_PHASES.findIndex((phase) => phase.includes(stage));
    if (index < 0) index = 0;
    elements["stage-timeline"].querySelectorAll("li").forEach((item, itemIndex) => {
      const phaseStages = item.dataset.stages.split(" ");
      const isCurrentPhase = phaseStages.includes(stage) || itemIndex === index;
      item.classList.toggle("done", itemIndex < index);
      item.classList.toggle("active", isCurrentPhase && !failed);
      item.classList.toggle("failed", isCurrentPhase && failed);
    });
  }

  function addRuntimeEvent(event) {
    state.events.push(event);
    elements["event-count"].textContent = `${state.events.length} events`;
    if (state.events.length === 1) elements["event-log"].replaceChildren();
    const item = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = new Date(event.created_at).toLocaleTimeString("ko-KR", { hour12: false });
    const message = document.createElement("span");
    message.textContent = `[${event.stage}] ${event.message}`;
    item.append(time, message);
    elements["event-log"].append(item);
    updateStage(event.stage, event.status === "failed");
    elements["current-stage"].textContent = event.stage;
    elements["global-stage"].textContent = event.stage;
  }

  function connectEvents() {
    closeEvents();
    const stream = new EventSource(`/api/experiments/${state.experimentId}/events`);
    state.eventSource = stream;
    stream.addEventListener("runtime", (event) => addRuntimeEvent(JSON.parse(event.data)));
    stream.addEventListener("job", async (event) => {
      const job = JSON.parse(event.data);
      closeEvents();
      try {
        renderJob(await api(`/api/experiments/${job.experiment_id}`));
      } catch (error) {
        showError(error);
      }
    });
    stream.onerror = () => {
      if (!state.job || !TERMINAL.has(state.job.status)) elements["control-error"].textContent = "실시간 이벤트 연결을 재시도하고 있습니다.";
    };
  }

  function closeEvents() {
    if (state.eventSource) state.eventSource.close();
    state.eventSource = null;
  }

  function startTimer(createdAt) {
    stopTimer();
    state.startedAt = createdAt ? new Date(createdAt) : new Date();
    const tick = () => {
      const seconds = Math.max(0, Math.floor((Date.now() - state.startedAt.getTime()) / 1000));
      elements["elapsed-time"].textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    };
    tick();
    state.timer = window.setInterval(tick, 1000);
  }

  function stopTimer() {
    if (state.timer) window.clearInterval(state.timer);
    state.timer = null;
  }

  async function runExperiment() {
    elements["control-error"].textContent = "";
    const item = scenario();
    const payload = {
      scenario_id: state.selectedScenario,
      namespace: item.namespace,
      deployment: item.deployment,
      metric: item.metric,
      threshold: item.threshold,
      mode: state.selectedMode,
      backend: "python",
      protocol_profile: controllerProfile(),
      repetitions: Number(elements["repetitions-select"].value),
      controller: elements["controller-select"].value,
      model: elements["model-input"].value.trim(),
      incident_source: item.incident_source || "chaos_mesh",
      benchmark_id: item.benchmark_id || "",
    };
    if (state.selectedMode === "real") {
      const confirmation = window.prompt("실제 Kubernetes 장애 주입과 복구를 실행하려면 EXECUTE REAL EXPERIMENT를 입력하세요.");
      if (confirmation !== "EXECUTE REAL EXPERIMENT") return;
      Object.assign(payload, { real_confirmation: "EXECUTE REAL EXPERIMENT" });
    }
    try {
      const job = await api("/api/experiments", { method: "POST", body: JSON.stringify(payload) });
      state.events = [];
      renderJob(job);
      startTimer(job.created_at);
      connectEvents();
    } catch (error) {
      showError(error);
    }
  }

  async function cancelExperiment() {
    if (!state.experimentId) return;
    try {
      const job = await api(`/api/experiments/${state.experimentId}/cancel`, { method: "POST" });
      renderJob(job);
    } catch (error) {
      showError(error);
    }
  }

  function showError(error) {
    elements["control-error"].textContent = error instanceof Error ? error.message : String(error);
  }

  function renderResearchDocuments() {
    elements["research-documents"].replaceChildren(...RESEARCH_DOCUMENTS.map((documentInfo) => {
      const link = document.createElement("a");
      link.href = `/api/artifacts/${documentInfo.sourcePath}`;
      link.target = "_blank";
      link.rel = "noreferrer";
      const type = document.createElement("b");
      type.textContent = documentInfo.text;
      const label = document.createElement("span");
      label.textContent = documentInfo.label;
      link.append(type, label);
      return link;
    }));
  }

  function renderAIOpsLabJob(job) {
    state.aiopslabJob = job;
    state.aiopslabJobId = job.job_id;
    const running = !TERMINAL.has(job.status);
    elements["aiopslab-job-status"].textContent = jobStatusLabel(job.status);
    elements["aiopslab-run"].disabled = running || !state.aiopslabRuntimeReady;
    elements["aiopslab-cancel"].disabled = !running;
    elements["aiopslab-runtime-status"].textContent = running
      ? `${job.current_stage} · 실행 중`
      : (state.aiopslabRuntimeReady ? "실행 가능" : "런타임 미준비");
    const result = job.result || {};
    elements["aiopslab-accuracy"].textContent = result.accuracy == null
      ? "—"
      : `${(Number(result.accuracy) * 100).toFixed(1)}%`;
    elements["aiopslab-ttd"].textContent = result.average_ttd == null
      ? "—"
      : `${Number(result.average_ttd).toFixed(3)}s`;
    elements["aiopslab-steps"].textContent = result.average_steps == null
      ? "—"
      : Number(result.average_steps).toFixed(2);
    elements["aiopslab-reward"].textContent = result.average_final_reward == null
      ? "—"
      : Number(result.average_final_reward).toFixed(3);
    renderAIOpsLabArtifacts(job.artifact_urls || {});
    if (job.error) elements["aiopslab-error"].textContent = job.error;
    if (TERMINAL.has(job.status)) closeAIOpsLabEvents();
  }

  function renderAIOpsLabArtifacts(artifactUrls) {
    const labels = {
      markdown: "요약 Markdown",
      csv: "결과 CSV",
    };
    const links = Object.entries(artifactUrls).map(([name, href]) => {
      const link = document.createElement("a");
      link.href = href;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = labels[name] || `Report ${name.replace("report-", "")}`;
      return link;
    });
    elements["aiopslab-artifacts"].replaceChildren(...links);
  }

  function addAIOpsLabEvent(event) {
    state.aiopslabEvents.push(event);
    elements["aiopslab-event-count"].textContent = `${state.aiopslabEvents.length} events`;
    if (state.aiopslabEvents.length === 1) {
      elements["aiopslab-event-log"].replaceChildren();
    }
    const item = document.createElement("li");
    const repetition = event.payload && event.payload.repetition
      ? ` · ${event.payload.repetition}회차`
      : "";
    item.textContent = `[${event.stage}] ${event.message}${repetition}`;
    elements["aiopslab-event-log"].append(item);
    elements["aiopslab-runtime-status"].textContent = `${event.stage} · 실행 중`;
  }

  function connectAIOpsLabEvents() {
    closeAIOpsLabEvents();
    const stream = new EventSource(`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/events`);
    state.aiopslabEventSource = stream;
    stream.addEventListener("benchmark", (event) => addAIOpsLabEvent(JSON.parse(event.data)));
    stream.addEventListener("job", async (event) => {
      const job = JSON.parse(event.data);
      closeAIOpsLabEvents();
      try {
        renderAIOpsLabJob(await api(`/api/benchmarks/aiopslab/jobs/${job.job_id}`));
      } catch (error) {
        elements["aiopslab-error"].textContent = error.message || String(error);
      }
    });
    stream.onerror = () => {
      if (!state.aiopslabJob || !TERMINAL.has(state.aiopslabJob.status)) {
        elements["aiopslab-error"].textContent = "Benchmark 이벤트 연결을 재시도하고 있습니다.";
      }
    };
  }

  function closeAIOpsLabEvents() {
    if (state.aiopslabEventSource) state.aiopslabEventSource.close();
    state.aiopslabEventSource = null;
  }

  async function loadAIOpsLabBenchmarks() {
    try {
      const payload = await api("/api/benchmarks/aiopslab");
      state.aiopslabCatalog = payload.benchmarks || [];
      state.aiopslabRuntimeReady = Boolean(payload.runtime && payload.runtime.ready);
      elements["aiopslab-benchmark-select"].replaceChildren(...state.aiopslabCatalog.map((benchmark) => {
        const option = document.createElement("option");
        option.value = benchmark.id;
        option.textContent = `${benchmark.title} · ${benchmark.problem_id}`;
        return option;
      }));
      const reason = payload.runtime && payload.runtime.reasons && payload.runtime.reasons[0];
      elements["aiopslab-runtime-status"].textContent = state.aiopslabRuntimeReady
        ? "실행 가능"
        : `미준비 · ${reason || "서버 환경 확인 필요"}`;
      elements["aiopslab-summary"].textContent = state.aiopslabRuntimeReady
        ? "AIOpsLab Detection Benchmark 준비"
        : "AIOpsLab Detection Benchmark 런타임 미준비";
      elements["aiopslab-run"].disabled = !state.aiopslabRuntimeReady;
      elements["aiopslab-run"].title = state.aiopslabRuntimeReady ? "" : (reason || "런타임 미준비");
    } catch (error) {
      state.aiopslabRuntimeReady = false;
      elements["aiopslab-runtime-status"].textContent = "연결 실패";
      elements["aiopslab-summary"].textContent = "AIOpsLab Detection Benchmark 연결 실패";
      elements["aiopslab-run"].disabled = true;
    }
  }

  async function runAIOpsLabBenchmark() {
    elements["aiopslab-error"].textContent = "";
    try {
      const job = await api("/api/benchmarks/aiopslab/jobs", {
        method: "POST",
        body: JSON.stringify({
          benchmark_id: elements["aiopslab-benchmark-select"].value,
          repetitions: Number(elements["aiopslab-repetitions"].value),
        }),
      });
      state.aiopslabEvents = [];
      elements["aiopslab-event-log"].replaceChildren();
      elements["aiopslab-benchmark-panel"].open = true;
      renderAIOpsLabJob(job);
      connectAIOpsLabEvents();
    } catch (error) {
      elements["aiopslab-error"].textContent = error.message || String(error);
    }
  }

  async function cancelAIOpsLabBenchmark() {
    if (!state.aiopslabJobId) return;
    try {
      const job = await api(`/api/benchmarks/aiopslab/jobs/${state.aiopslabJobId}/cancel`, {
        method: "POST",
      });
      renderAIOpsLabJob(job);
    } catch (error) {
      elements["aiopslab-error"].textContent = error.message || String(error);
    }
  }

  async function restoreLatestAIOpsLabJob() {
    try {
      const payload = await api("/api/benchmarks/aiopslab/jobs?limit=20");
      const latest = payload.jobs && payload.jobs[0];
      if (!latest) return;
      const job = await api(`/api/benchmarks/aiopslab/jobs/${latest.job_id}`);
      state.aiopslabEvents = [];
      elements["aiopslab-event-log"].replaceChildren();
      (job.events || []).forEach((event) => addAIOpsLabEvent(event));
      renderAIOpsLabJob(job);
      if (!TERMINAL.has(job.status)) connectAIOpsLabEvents();
    } catch (_error) {
      return;
    }
  }

  function renderComparisonJob(job) {
    state.comparisonJob = job;
    state.comparisonJobId = job.job_id;
    const running = !TERMINAL.has(job.status);
    const result = job.result || {};
    const statistics = result.statistics || {};
    const overall = statistics.overall || {};
    const total = Number(result.total_treatments || (job.request.repetitions * 12) || 0);
    const progressEvents = state.comparisonEvents
      .map((event) => Number(event.payload && event.payload.completed_treatments || 0));
    const completed = TERMINAL.has(job.status)
      ? Number(result.total_treatments || 0)
      : Math.max(0, ...progressEvents);
    elements["comparison-job-status"].textContent = jobStatusLabel(job.status);
    elements["comparison-progress"].textContent = `${completed} / ${total}`;
    elements["comparison-success-rate"].textContent = overall.success_rate == null
      ? "—"
      : `${(Number(overall.success_rate) * 100).toFixed(1)}%`;
    elements["comparison-mean-recovery"].textContent = overall.mean_recovery_seconds == null
      ? "—"
      : `${Number(overall.mean_recovery_seconds).toFixed(2)}s`;
    elements["comparison-evidence"].textContent = result.evidence_type === "real_cluster"
      ? "Real cluster"
      : (result.evidence_type === "synthetic_mock" ? "합성 Mock" : "—");
    elements["comparison-run"].disabled = running;
    elements["comparison-cancel"].disabled = !running;
    elements["comparison-runtime-status"].textContent = running
      ? `${job.current_stage} · ${completed}/${total}`
      : jobStatusLabel(job.status);
    renderComparisonArtifacts(job.artifact_urls || {});
    renderComparisonCharts(job.artifact_urls || {}, job.updated_at);
    if (job.error) elements["comparison-error"].textContent = job.error;
    if (TERMINAL.has(job.status)) closeComparisonEvents();
  }

  function renderComparisonCharts(artifactUrls, version) {
    const charts = [
      ["comparison-success-chart", artifactUrls.success_rate_png],
      ["comparison-recovery-chart", artifactUrls.recovery_seconds_png],
    ];
    charts.forEach(([id, href]) => {
      if (href) elements[id].src = `${href}?v=${encodeURIComponent(version || "latest")}`;
      else elements[id].removeAttribute("src");
    });
  }

  function renderComparisonArtifacts(artifactUrls) {
    const labels = {
      outcomes_jsonl: "Outcomes JSONL",
      reward_markdown: "Reward 정책표",
      reward_csv: "Reward CSV",
      quantitative_markdown: "정량 요약",
      scenario_action_csv: "Scenario·Action CSV",
      policy_reward_csv: "정책 통계 CSV",
      success_rate_png: "성공률 PNG",
      recovery_seconds_png: "복구 시간 PNG",
      reward_policy_png: "Reward PNG",
    };
    const links = Object.entries(artifactUrls)
      .filter(([name]) => labels[name])
      .map(([name, href]) => {
        const link = document.createElement("a");
        link.href = href;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = labels[name];
        return link;
      });
    elements["comparison-artifacts"].replaceChildren(...links);
  }

  function addComparisonEvent(event) {
    state.comparisonEvents.push(event);
    elements["comparison-event-count"].textContent = `${state.comparisonEvents.length} events`;
    if (state.comparisonEvents.length === 1) elements["comparison-event-log"].replaceChildren();
    const item = document.createElement("li");
    const payload = event.payload || {};
    const progress = payload.total_treatments
      ? ` · ${payload.completed_treatments || 0}/${payload.total_treatments}`
      : "";
    item.textContent = `[${event.stage}] ${event.message}${progress}`;
    elements["comparison-event-log"].append(item);
    if (payload.total_treatments) {
      elements["comparison-progress"].textContent = `${payload.completed_treatments || 0} / ${payload.total_treatments}`;
      elements["comparison-runtime-status"].textContent = `${event.stage} · ${payload.completed_treatments || 0}/${payload.total_treatments}`;
    }
  }

  function connectComparisonEvents() {
    closeComparisonEvents();
    const stream = new EventSource(`/api/comparisons/recovery/jobs/${state.comparisonJobId}/events`);
    state.comparisonEventSource = stream;
    stream.addEventListener("comparison", (event) => addComparisonEvent(JSON.parse(event.data)));
    stream.addEventListener("job", async (event) => {
      const job = JSON.parse(event.data);
      closeComparisonEvents();
      try {
        renderComparisonJob(await api(`/api/comparisons/recovery/jobs/${job.job_id}`));
      } catch (error) {
        elements["comparison-error"].textContent = error.message || String(error);
      }
    });
    stream.onerror = () => {
      if (!state.comparisonJob || !TERMINAL.has(state.comparisonJob.status)) {
        elements["comparison-error"].textContent = "비교 실험 이벤트 연결을 재시도하고 있습니다.";
      }
    };
  }

  function closeComparisonEvents() {
    if (state.comparisonEventSource) state.comparisonEventSource.close();
    state.comparisonEventSource = null;
  }

  function updateComparisonModeBoundary() {
    const mode = elements["comparison-mode"].value;
    const runtime = state.comparisonRuntime[mode] || {};
    elements["comparison-boundary"].textContent = mode === "real"
      ? "Real은 Ubuntu에서 Chaos Mesh 장애를 실제 주입하고 Prometheus·Kubernetes 결과를 측정합니다. 서버 Gate와 확인 문구가 모두 필요합니다."
      : "Mock은 UI와 분석 파이프라인 검증용 합성 비교 데이터입니다. 논문 근거는 Ubuntu Real 실행 결과만 사용합니다.";
    elements["comparison-runtime-status"].textContent = runtime.ready
      ? (mode === "real" ? "Real 실행 가능" : "Mock 실행 가능")
      : `미준비 · ${(runtime.reasons && runtime.reasons[0]) || "서버 환경 확인 필요"}`;
    elements["comparison-run"].disabled = !runtime.ready;
  }

  async function loadRecoveryComparison() {
    try {
      const payload = await api("/api/comparisons/recovery");
      state.comparisonRuntime = payload.runtime_modes || {};
      updateComparisonModeBoundary();
    } catch (error) {
      elements["comparison-runtime-status"].textContent = "연결 실패";
      elements["comparison-run"].disabled = true;
    }
  }

  async function runRecoveryComparison() {
    elements["comparison-error"].textContent = "";
    const mode = elements["comparison-mode"].value;
    let realConfirmation = "";
    if (mode === "real") {
      realConfirmation = window.prompt(
        "실제 36회 비교 실험을 실행하려면 EXECUTE REAL COMPARISON을 입력하세요.",
        ""
      ) || "";
      if (realConfirmation !== "EXECUTE REAL COMPARISON") return;
    }
    try {
      const job = await api("/api/comparisons/recovery/jobs", {
        method: "POST",
        body: JSON.stringify({
          repetitions: Number(elements["comparison-repetitions"].value),
          mode,
          guard_backend: elements["comparison-guard"].value,
          real_confirmation: realConfirmation,
        }),
      });
      state.comparisonEvents = [];
      elements["comparison-event-log"].replaceChildren();
      elements["recovery-comparison-panel"].open = true;
      renderComparisonJob(job);
      connectComparisonEvents();
    } catch (error) {
      elements["comparison-error"].textContent = error.message || String(error);
    }
  }

  async function cancelRecoveryComparison() {
    if (!state.comparisonJobId) return;
    try {
      const job = await api(`/api/comparisons/recovery/jobs/${state.comparisonJobId}/cancel`, { method: "POST" });
      renderComparisonJob(job);
    } catch (error) {
      elements["comparison-error"].textContent = error.message || String(error);
    }
  }

  async function restoreLatestRecoveryComparison() {
    try {
      const payload = await api("/api/comparisons/recovery/jobs?limit=20");
      const latest = payload.jobs && payload.jobs[0];
      if (!latest) return;
      const job = await api(`/api/comparisons/recovery/jobs/${latest.job_id}`);
      state.comparisonEvents = [];
      elements["comparison-event-log"].replaceChildren();
      (job.events || []).forEach((event) => addComparisonEvent(event));
      renderComparisonJob(job);
      if (!TERMINAL.has(job.status)) connectComparisonEvents();
    } catch (error) {
      elements["comparison-error"].textContent = `최근 비교 Job 복원 실패: ${error.message || String(error)}`;
    }
  }

  async function loadScenarios() {
    try {
      const payload = await api("/api/scenarios");
      const resolved = {};
      (payload.scenarios || []).forEach((item) => {
        const id = item.scenario_id || item.id;
        if (id) resolved[id] = normalizeScenario(item);
      });
      if (Object.keys(resolved).length) state.scenarios = resolved;
    } catch (_error) {
      state.scenarios = { ...REGISTERED_SCENARIOS };
    }
    renderScenarioButtons();
    renderCondition();
  }

  async function loadConnections() {
    try {
      const payload = await api("/api/connections");
      const connections = payload.connections || {};
      state.connections = connections;
      const values = Object.entries(connections);
      const required = values.filter(([, item]) => item.required_for_real);
      const ready = required.filter(([, item]) => item.ready).length;
      elements["connection-label"].textContent = `${ready}/${required.length} 실험 연결 준비`;
      elements["connection-summary"].textContent = `Prometheus · Chaos Mesh · Kubernetes ${ready === required.length ? "준비" : "일부 미연결"}`;
      elements["connection-dot"].classList.toggle("ready", ready === required.length);
      const autogen = connections.autogen || { ready: false, reason: "AutoGen 연결 정보 없음" };
      elements["autogen-controller-state"].textContent = autogen.ready ? "Ready" : "설정 필요";
      elements["autogen-controller-state"].classList.toggle("is-ready", Boolean(autogen.ready));
      elements["autogen-summary"].textContent = autogen.ready
        ? "AutoGen GroupChat 준비"
        : `AutoGen 미준비 · ${autogen.reason || "연결 필요"}`;
      elements["controller-readiness"].textContent = autogen.reason || "AutoGen 연결 상태 확인 완료";
      selectController(elements["controller-select"].value);
    } catch (_error) {
      elements["connection-label"].textContent = "연결 정보 없음";
      elements["autogen-controller-state"].textContent = "확인 실패";
    }
  }

  async function restoreLatestJob() {
    try {
      const payload = await api("/api/experiments?limit=20");
      const latest = payload.jobs && payload.jobs[0];
      if (!latest) return;
      const job = await api(`/api/experiments/${latest.experiment_id}`);
      renderJob(job);
      const restoredEvents = job.events || [];
      state.events = [];
      elements["event-log"].replaceChildren();
      restoredEvents.forEach((event) => addRuntimeEvent(event));
      if (!TERMINAL.has(job.status)) {
        startTimer(job.started_at || job.created_at);
        connectEvents();
      }
    } catch (error) {
      showError(error);
    }
  }

  function bindControls() {
    bindPlatformNavigation();
    elements["mode-control"].querySelectorAll("button[data-mode]").forEach((button) => button.addEventListener("click", () => selectMode(button.dataset.mode)));
    elements["controller-select"].addEventListener("change", (event) => selectController(event.target.value));
    elements["controller-options"].querySelectorAll("button[data-controller]").forEach((button) => button.addEventListener("click", () => selectController(button.dataset.controller)));
    elements["agent-grid"].querySelectorAll("button[data-agent]").forEach((button) => button.addEventListener("click", () => selectAgent(button.dataset.agent)));
    elements["agent-tabs"].querySelectorAll("button[data-agent-tab]").forEach((button) => button.addEventListener("click", () => selectAgent(button.dataset.agentTab)));
    elements["run-experiment"].addEventListener("click", runExperiment);
    elements["cancel-experiment"].addEventListener("click", cancelExperiment);
    elements["comparison-mode"].addEventListener("change", updateComparisonModeBoundary);
    elements["comparison-run"].addEventListener("click", runRecoveryComparison);
    elements["comparison-cancel"].addEventListener("click", cancelRecoveryComparison);
  }

  async function boot() {
    bindControls();
    renderResearchDocuments();
    elements["comparison-artifacts"].title = COMPARISON_BOUNDARY_NOTE;
    renderCondition();
    resetEvidenceView();
    await Promise.all([
      loadScenarios(),
      loadConnections(),
      loadRecoveryComparison(),
    ]);
    await Promise.all([
      restoreLatestJob(),
      restoreLatestRecoveryComparison(),
    ]);
  }

  window.addEventListener("beforeunload", () => {
    closeEvents();
    closeComparisonEvents();
  });
  boot();
})();
