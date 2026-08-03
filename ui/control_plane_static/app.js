(function () {
  "use strict";

  const REGISTERED_SCENARIOS = {
    "cpu-stress": { label: "CPU Stress", namespace: "online-boutique", deployment: "paymentservice", metric: "cpu", threshold: 80 },
    "memory-stress": { label: "Memory Stress", namespace: "online-boutique", deployment: "checkoutservice", metric: "memory", threshold: 80 },
    "network-delay": { label: "Network Delay", namespace: "online-boutique", deployment: "paymentservice", metric: "latency", threshold: 0.1 },
    "pod-kill": { label: "Pod Kill", namespace: "online-boutique", deployment: "paymentservice", metric: "availability", threshold: 1 },
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

  const AIOPSLAB_BOUNDARY_NOTE = "AIOpsLab Detection Benchmark는 Kubernetes 복구 실험과 별도로 기록됩니다.";

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

  const STAGE_ORDER = [
    "preflight",
    "injecting_fault",
    "collecting_evidence",
    "agent_reasoning",
    "validating",
    "executing",
    "observing_recovery",
  ];

  const TERMINAL = new Set(["completed", "failed", "blocked", "cancelled", "interrupted"]);
  const state = {
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
    aiopslabCatalog: [],
    aiopslabRuntimeReady: false,
    aiopslabJobId: "",
    aiopslabJob: null,
    aiopslabEventSource: null,
    aiopslabEvents: [],
  };

  const elements = Object.fromEntries([
    "connection-dot", "connection-label", "connection-summary", "experiment-id",
    "job-status", "current-stage", "consensus-status", "safety-status",
    "scenario-list", "mode-control", "controller-select", "profile-select",
    "controller-model", "model-input", "controller-readiness",
    "repetitions-select", "target-deployment", "target-metric", "mode-boundary",
    "run-experiment", "cancel-experiment", "control-error", "elapsed-time",
    "stage-timeline", "evidence-scenario", "evidence-target", "evidence-metric",
    "evidence-source", "agent-grid", "review-summary", "consensus-summary",
    "action-summary", "event-count", "event-log", "agent-tabs", "selected-agent",
    "agent-decision", "agent-approval", "agent-reward", "agent-statement",
    "peer-reviews", "controller-provenance", "autogen-transcript-panel",
    "autogen-transcript", "allowlist-result", "validator-result", "cleanup-result",
    "result-status", "result-recovery", "result-mttr", "result-reward",
    "result-reviews", "result-artifacts", "research-documents", "autogen-summary",
    "aiopslab-summary", "aiopslab-benchmark-panel", "aiopslab-runtime-status",
    "aiopslab-benchmark-select", "aiopslab-repetitions", "aiopslab-run",
    "aiopslab-cancel", "aiopslab-job-status", "aiopslab-accuracy",
    "aiopslab-ttd", "aiopslab-steps", "aiopslab-reward",
    "aiopslab-event-count", "aiopslab-event-log", "aiopslab-artifacts",
    "aiopslab-error",
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
    };
  }

  function setPressed(container, selector, selected) {
    container.querySelectorAll(selector).forEach((button) => {
      const value = button.dataset.scenario || button.dataset.mode || button.dataset.agent || button.dataset.agentTab;
      button.setAttribute("aria-pressed", String(value === selected));
    });
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
      metadata.textContent = `${item.deployment} · ${item.metric}`;
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
  }

  function controllerProfile() {
    return elements["controller-select"].value === "autogen"
      ? "four-agent-autogen-v1"
      : elements["profile-select"].value;
  }

  function selectController(controller) {
    if (state.running) return;
    const autogen = state.connections.autogen || { ready: false, reason: "AutoGen 연결 정보 없음" };
    if (controller === "autogen" && !autogen.ready) {
      elements["controller-select"].value = "deterministic";
      elements["control-error"].textContent = autogen.reason || "AutoGen runtime is not ready";
      return;
    }
    const isAutogen = controller === "autogen";
    elements["controller-model"].hidden = !isAutogen;
    elements["profile-select"].disabled = isAutogen;
    elements["profile-select"].value = isAutogen
      ? "four-agent-autogen-v1"
      : "four-agent-role-veto-v1";
    elements["controller-readiness"].textContent = isAutogen
      ? (autogen.reason || "AutoGen runtime 준비")
      : "Deterministic 4-Agent runtime";
    elements["control-error"].textContent = "";
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
  }

  function resetEvidenceView() {
    elements["evidence-metric"].textContent = "실험 Evidence 수집 후 표시";
    elements["evidence-source"].textContent = state.selectedMode === "real" ? "Prometheus + Kubernetes" : "FakeEvidenceProvider";
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
      elements["controller-select"].value = job.request.controller || "deterministic";
      elements["model-input"].value = job.request.model || elements["model-input"].value;
      elements["profile-select"].value = job.request.protocol_profile || "four-agent-role-veto-v1";
      elements["controller-model"].hidden = job.request.controller !== "autogen";
      elements["profile-select"].disabled = job.request.controller === "autogen";
    }
    elements["experiment-id"].textContent = job.experiment_id;
    elements["job-status"].textContent = jobStatusLabel(job.status);
    elements["current-stage"].textContent = job.current_stage;
    elements["run-experiment"].disabled = state.running;
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
    const metrics = evidence.metric_values || {};
    const metricEntries = Object.entries(metrics);
    elements["evidence-metric"].textContent = metricEntries.length ? metricEntries.map(([key, value]) => `${key} ${formatValue(value)}`).join(" · ") : "수집 결과 없음";
    elements["evidence-source"].textContent = evidence.source || "unknown";
    const reviews = Array.isArray(report.peer_reviews) ? report.peer_reviews : [];
    elements["review-summary"].textContent = `${reviews.length}개 역할별 검토`;
    const negotiation = report.negotiation || {};
    elements["consensus-summary"].textContent = negotiation.consensus || "미합의";
    elements["consensus-status"].textContent = negotiation.consensus === "approved" ? "합의 완료" : "합의 확인 필요";
    elements["action-summary"].textContent = actionLabel(report.selected_action);
    const safety = report.safety_validation || {};
    elements["allowlist-result"].textContent = safety.valid === true ? "통과" : "차단/대기";
    elements["validator-result"].textContent = safety.valid === true ? "VALID" : "대기";
    elements["safety-status"].textContent = safety.valid === true ? "안전 검증 통과" : "검증 미완료";
    const cleanup = report.cleanup || {};
    elements["cleanup-result"].textContent = cleanup.valid === false ? "실패 · 검토 필요" : "완료/불필요";
    const recovery = report.recovery_monitoring || {};
    elements["result-status"].textContent = report.final_status || "완료";
    elements["result-recovery"].textContent = recovery.recovery_success === true ? "성공" : (recovery.recovery_success === false ? "실패" : "—");
    elements["result-mttr"].textContent = recovery.recovery_seconds == null ? "—" : `${recovery.recovery_seconds}s`;
    const contributions = Object.values(report.agent_contributions || {});
    const reward = contributions.reduce((sum, item) => sum + Number(item.reward || 0), 0);
    elements["result-reward"].textContent = contributions.length ? reward.toFixed(3) : "—";
    elements["result-reviews"].textContent = String(reviews.length);
    const artifacts = Object.keys(report.artifacts || {});
    elements["result-artifacts"].textContent = artifacts.length ? `${artifacts.length}개` : "Job DB 저장";
  }

  function formatValue(value) {
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
    return String(value);
  }

  function jobStatusLabel(status) {
    return ({ queued: "대기", running: "실행 중", cancelling: "취소 중", completed: "완료", failed: "실패", blocked: "안전 차단", cancelled: "취소됨", interrupted: "서버 재시작으로 중단" })[status] || status;
  }

  function updateStage(stage, failed) {
    let index = STAGE_ORDER.indexOf(stage);
    if (stage === "cleanup" || stage === "completed") index = STAGE_ORDER.length - 1;
    elements["stage-timeline"].querySelectorAll("li").forEach((item, itemIndex) => {
      item.classList.toggle("done", itemIndex < index);
      item.classList.toggle("active", itemIndex === index && !failed);
      item.classList.toggle("failed", itemIndex === index && failed);
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
      const autogenOption = elements["controller-select"].querySelector('option[value="autogen"]');
      autogenOption.disabled = !autogen.ready;
      autogenOption.title = autogen.reason || "";
      elements["autogen-summary"].textContent = autogen.ready
        ? "AutoGen GroupChat 준비"
        : `AutoGen 미준비 · ${autogen.reason || "연결 필요"}`;
      elements["controller-readiness"].textContent = autogen.reason || "AutoGen 연결 상태 확인 완료";
    } catch (_error) {
      elements["connection-label"].textContent = "연결 정보 없음";
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
    elements["mode-control"].querySelectorAll("button[data-mode]").forEach((button) => button.addEventListener("click", () => selectMode(button.dataset.mode)));
    elements["controller-select"].addEventListener("change", (event) => selectController(event.target.value));
    elements["agent-grid"].querySelectorAll("button[data-agent]").forEach((button) => button.addEventListener("click", () => selectAgent(button.dataset.agent)));
    elements["agent-tabs"].querySelectorAll("button[data-agent-tab]").forEach((button) => button.addEventListener("click", () => selectAgent(button.dataset.agentTab)));
    elements["run-experiment"].addEventListener("click", runExperiment);
    elements["cancel-experiment"].addEventListener("click", cancelExperiment);
    elements["aiopslab-run"].addEventListener("click", runAIOpsLabBenchmark);
    elements["aiopslab-cancel"].addEventListener("click", cancelAIOpsLabBenchmark);
  }

  async function boot() {
    bindControls();
    renderResearchDocuments();
    elements["result-artifacts"].title = AIOPSLAB_BOUNDARY_NOTE;
    renderCondition();
    resetEvidenceView();
    await Promise.all([loadScenarios(), loadConnections(), loadAIOpsLabBenchmarks()]);
    await Promise.all([restoreLatestJob(), restoreLatestAIOpsLabJob()]);
  }

  window.addEventListener("beforeunload", () => {
    closeEvents();
    closeAIOpsLabEvents();
  });
  boot();
})();
