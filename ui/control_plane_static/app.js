(function () {
  "use strict";

  const root = document.getElementById("root");

  const FALLBACK_SCENARIOS = [
    {
      scenario_id: "cpu-stress",
      label: "CPU Stress",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "cpu",
      value: 95,
      threshold: 80,
      event: "StressChaos · CPU workers=2",
      source: "Prometheus + K8s",
      summary: "CPU 포화 상태에서 역할별 판단과 bounded recovery Action을 검증합니다.",
      chart: [18, 22, 31, 69, 91, 84, 94, 86],
    },
    {
      scenario_id: "memory-stress",
      label: "Memory Stress",
      namespace: "online-boutique",
      deployment: "checkoutservice",
      metric: "memory",
      value: 95.7,
      threshold: 80,
      event: "StressChaos · Memory 80MB",
      source: "Prometheus + K8s",
      summary: "메모리 포화와 OOM 위험에 대한 복구 판단을 검증합니다.",
      chart: [24, 30, 38, 61, 88, 96, 91, 72],
    },
    {
      scenario_id: "network-delay",
      label: "Network Delay",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "latency",
      value: 0.234,
      threshold: 0.1,
      event: "NetworkChaos · delay 200ms",
      source: "Blackbox + K8s",
      summary: "서비스 지연 Evidence에 대한 원인 진단과 복구 후 평가를 검증합니다.",
      chart: [18, 20, 22, 34, 71, 92, 48, 24],
    },
    {
      scenario_id: "pod-kill",
      label: "Pod Kill",
      namespace: "online-boutique",
      deployment: "paymentservice",
      metric: "availability",
      value: 0,
      threshold: 1,
      event: "PodChaos · one pod",
      source: "Kubernetes snapshot",
      summary: "Pod 종료 후 Kubernetes 자체 복구와 Agent 추가 조치를 비교합니다.",
      chart: [100, 100, 100, 0, 38, 72, 100, 100],
    },
  ];

  const AGENT_META = {
    AIServiceHASupportAgent: {
      code: "HA",
      short: "HA Agent",
      label: "AI서비스 HA 지원 에이전트",
      phase: "진단",
      scope: "availability",
      tone: "blue",
      role: "장애 원인과 가용성 위험을 진단하고 복구 필요성을 판단합니다.",
    },
    AIApplicationManagementAgent: {
      code: "APP",
      short: "Application",
      label: "AI응용관리 자동화 에이전트",
      phase: "제안",
      scope: "action_validity",
      tone: "clay",
      role: "진단 결과를 bounded Kubernetes 복구 Action으로 변환합니다.",
    },
    AISemiconductorInfraOpsAgent: {
      code: "INF",
      short: "Infrastructure",
      label: "AI인프라 운용 에이전트",
      phase: "검토",
      scope: "resource_safety",
      tone: "clay",
      role: "Replica와 자원 용량이 인프라 안전 정책을 만족하는지 검토합니다.",
    },
    CostOptimizationAgent: {
      code: "CST",
      short: "Cost",
      label: "비용 최적화 지원 에이전트",
      phase: "검토",
      scope: "budget",
      tone: "clay",
      role: "복구 Action이 과잉 대응이나 비용 한도 초과인지 검토합니다.",
    },
  };

  const DEFAULT_ACTIONS = {
    "cpu-stress": { kind: "scale_out", replicas: 3 },
    "memory-stress": { kind: "rollout_restart", replicas: null },
    "network-delay": { kind: "rollout_restart", replicas: null },
    "pod-kill": { kind: "observe_only", replicas: null },
  };

  const DEFAULT_DIAGNOSIS = {
    "cpu-stress": { cause: "cpu_saturation", severity: "critical", confidence: 0.88 },
    "memory-stress": { cause: "memory_pressure", severity: "critical", confidence: 0.9 },
    "network-delay": { cause: "network_latency", severity: "high", confidence: 0.86 },
    "pod-kill": { cause: "low_availability", severity: "high", confidence: 0.92 },
  };

  const RESEARCH_DOCUMENTS = [
    {
      label: "4-Agent 연구 보고서",
      path: "docs/deliverables/AIOps_4Agent_Research_Report.docx",
      sourcePath: "docs/core_submission_summary.md",
    },
    {
      label: "실험 운영 가이드",
      path: "docs/deliverables/AIOps_Experiment_Operations_Guide.docx",
      sourcePath: "docs/submission/execution_code_guide.md",
    },
    {
      label: "Agent 정책 명세서",
      path: "docs/deliverables/AIOps_Agent_Policy_Specification.docx",
      sourcePath: "docs/design/agent_action_reward_policy.md",
    },
  ];

  const state = {
    overview: null,
    agents: [],
    scenarios: FALLBACK_SCENARIOS,
    latestRun: null,
    currentSession: null,
    experimentHistory: [],
    selectedScenario: "cpu-stress",
    selectedAgent: "AIServiceHASupportAgent",
    backend: "python",
    repetitions: 3,
    running: false,
    lastError: "",
  };

  function h(tag, attrs, children) {
    const element = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value == null || value === false) return;
      if (key === "className") {
        element.className = value;
      } else if (key === "text") {
        element.textContent = value;
      } else if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "disabled") {
        element.disabled = Boolean(value);
      } else if (key === "selected") {
        element.selected = Boolean(value);
      } else {
        element.setAttribute(key, value === true ? "" : String(value));
      }
    });
    (children || []).filter(Boolean).forEach((child) => {
      element.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return element;
  }

  function svg(tag, attrs, children) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      element.setAttribute(key, String(value));
    });
    (children || []).filter(Boolean).forEach((child) => element.append(child));
    return element;
  }

  function selectedScenario() {
    return state.scenarios.find((item) => item.scenario_id === state.selectedScenario)
      || FALLBACK_SCENARIOS[0];
  }

  function stagePayload(session, key) {
    return session && session.stages && session.stages[key]
      ? session.stages[key].payload || {}
      : {};
  }

  function sessionForSelection() {
    const session = state.currentSession;
    return session
      && session.condition
      && session.condition.scenario === state.selectedScenario
      ? session
      : null;
  }

  function diagnosisFor(scenario, session) {
    return stagePayload(session, "diagnosis").diagnosis
      || DEFAULT_DIAGNOSIS[scenario.scenario_id];
  }

  function actionFor(scenario, session) {
    return stagePayload(session, "consensus").selected_action
      || DEFAULT_ACTIONS[scenario.scenario_id];
  }

  function evidenceFor(scenario, session) {
    const payload = stagePayload(session, "evidence");
    return {
      metric_values: payload.metric_values || { [scenario.metric]: scenario.value },
      desired_replicas: payload.desired_replicas == null ? 1 : payload.desired_replicas,
      available_replicas: payload.available_replicas == null ? 1 : payload.available_replicas,
      events: payload.events || [scenario.event],
      source: payload.source || scenario.source,
    };
  }

  function reviewsFor(session) {
    return stagePayload(session, "consensus").peer_reviews || [];
  }

  function decisionsFor(session) {
    return stagePayload(session, "diagnosis").initial_decisions || [];
  }

  function contributionFor(agentName, session) {
    return stagePayload(session, "result").agent_contributions?.[agentName] || {};
  }

  function render() {
    const scenario = selectedScenario();
    const session = sessionForSelection();
    root.replaceChildren(
      h("main", { className: "experiment-console" }, [
        consoleHeader(session),
        metricStrip(scenario, session),
        h("div", { className: "experiment-workspace" }, [
          scenarioRail(scenario, session),
          liveCanvas(scenario, session),
        ]),
        decisionInspector(scenario, session),
        experimentTimeline(session),
        researchDocuments(),
        consoleFooter(session),
      ])
    );
  }

  function consoleHeader(session) {
    const experimentId = session
      ? session.experiment_id.replace(/^run-/, "EXP-").slice(0, 20).toUpperCase()
      : "EXP-READY";
    return h("header", { className: "console-header" }, [
      h("div", { className: "identity-lockup" }, [
        h("span", { className: "product-mark", text: "AI" }),
        h("div", {}, [
          h("p", { className: "eyebrow", text: "AI-MCMP · 연구 운영" }),
          h("h1", { text: "4-Agent AIOps 실험 콘솔" }),
          h("p", {
            className: "header-description",
            text: "상호감시형 Agent 판단과 Kubernetes 복구를 하나의 실험 흐름으로 추적합니다.",
          }),
        ]),
      ]),
      h("div", { className: "header-actions" }, [
        h("div", { className: "runtime-status" }, [
          h("span", { className: "status-dot" }),
          h("strong", { text: "READY" }),
          h("span", { text: experimentId }),
          h("span", { className: "mode-pill", text: "MOCK SAFE" }),
        ]),
        h("button", {
          className: "run-button",
          type: "button",
          disabled: state.running,
          onClick: runScenario,
          text: state.running ? "실험 실행 중…" : "▷ 실험 실행",
        }),
      ]),
    ]);
  }

  function metricStrip(scenario, session) {
    const diagnosis = diagnosisFor(scenario, session);
    const consensus = stagePayload(session, "consensus");
    const safety = stagePayload(session, "safety");
    const result = stagePayload(session, "result");
    const metric = evidenceFor(scenario, session).metric_values[scenario.metric];

    return h("section", { className: "metric-strip", "aria-label": "실험 핵심 상태" }, [
      metricCard("장애 지표", metricHeadline(scenario, metric), `임계치 ${thresholdLabel(scenario)}`),
      metricCard(
        "Agent 합의",
        session && consensus.negotiation?.consensus === "approved" ? "4 / 4" : "대기",
        session ? `${reviewsFor(session).length}개 역할 검토 완료` : "역할별 검토 대기",
      ),
      metricCard(
        "안전 경계",
        safety.valid === true ? "VALID" : "준비",
        "allowlist · replica 1–5",
      ),
      metricCard(
        "복구 상태",
        result.recovery_monitoring?.recovery_success === true ? "복구 완료" : "대기",
        session ? statusLabel(session.status) : `${diagnosis.severity} 진단 준비`,
      ),
    ]);
  }

  function metricCard(label, value, note) {
    return h("article", { className: "metric-card" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
      h("small", { text: note }),
    ]);
  }

  function scenarioRail(scenario, session) {
    return h("aside", { className: "scenario-rail" }, [
      h("div", { className: "panel-heading" }, [
        h("div", {}, [
          h("p", { className: "eyebrow", text: "EXPERIMENT" }),
          h("h2", { text: "장애 시나리오" }),
        ]),
        h("span", { className: "flask-icon", text: "⌁" }),
      ]),
      h(
        "div",
        { className: "scenario-list", role: "group", "aria-label": "장애 시나리오 선택" },
        state.scenarios.map((item) =>
          h("button", {
            className: `scenario-choice${item.scenario_id === scenario.scenario_id ? " is-selected" : ""}`,
            type: "button",
            "data-scenario": item.scenario_id,
            "aria-pressed": item.scenario_id === scenario.scenario_id ? "true" : "false",
            onClick: () => selectScenario(item.scenario_id),
            text: normalizedScenario(item).label,
          })
        ),
      ),
      h("div", { className: "scenario-metadata" }, [
        metadataRow("대상", scenario.deployment),
        metadataRow("Namespace", scenario.namespace),
        metadataRow("반복", `${state.repetitions}회`),
        metadataRow(
          "프로파일",
          session ? session.protocol_profile.profile_id : "role-veto-v1",
        ),
        metadataRow("실행 모드", session ? session.mode : "mock"),
      ]),
      h("label", { className: "backend-field" }, [
        h("span", { text: "안전 검증" }),
        h("select", {
          "aria-label": "Guard backend",
          onChange: (event) => {
            state.backend = event.target.value;
            render();
          },
        }, [
          h("option", {
            value: "python",
            selected: state.backend === "python",
            text: "Python Validator",
          }),
          h("option", {
            value: "go",
            selected: state.backend === "go",
            text: "Python + Go Guard",
          }),
        ]),
      ]),
      state.lastError
        ? h("p", { className: "inline-error", text: state.lastError })
        : null,
    ]);
  }

  function liveCanvas(scenario, session) {
    const evidence = evidenceFor(scenario, session);
    const action = actionFor(scenario, session);
    const safety = stagePayload(session, "safety");
    const consensus = stagePayload(session, "consensus");

    return h("section", { className: "live-canvas" }, [
      h("div", { className: "canvas-heading" }, [
        h("div", {}, [
          h("p", { className: "eyebrow", text: "LIVE EXPERIMENT CANVAS" }),
          h("h2", { text: "운영 판단과 복구 흐름" }),
        ]),
        h("span", {
          className: `stage-badge${state.running ? " is-running" : ""}`,
          text: state.running ? "분석 중" : session ? "실험 완료" : "관측 준비",
        }),
      ]),
      evidenceStrip(scenario, evidence),
      h(
        "div",
        { className: "agent-flow-grid", "aria-label": "4-Agent 상호검토" },
        Object.keys(AGENT_META).map((agentName) =>
          agentFlowCard(agentName, scenario, session)
        ),
      ),
      h("div", { className: "decision-flow" }, [
        flowBlock("상호검토", session ? `${reviewsFor(session).length}개 역할 의견 수집` : "4개 역할 의견 수집"),
        h("span", { className: "flow-arrow", text: "→" }),
        flowBlock(
          "최종 Action",
          actionLabel(action),
          consensus.negotiation?.consensus === "approved" ? "합의 승인" : "합의 준비",
        ),
        h("span", { className: "flow-arrow", text: "→" }),
        flowBlock(
          "이중 안전 검증",
          session ? session.guard_backend : state.backend,
          safety.valid === true ? "정책 통과" : "검증 대기",
        ),
      ]),
      metricChart(scenario),
    ]);
  }

  function evidenceStrip(scenario, evidence) {
    const metricValue = evidence.metric_values[scenario.metric];
    return h("div", { className: "evidence-strip" }, [
      evidenceItem("Metric", `${scenario.metric} ${metricDisplay(scenario, metricValue)}`),
      evidenceItem(
        "Replica",
        `${evidence.desired_replicas} desired / ${evidence.available_replicas} ready`,
      ),
      evidenceItem("Event", scenario.event),
      evidenceItem("Source", evidence.source === "fake" ? "FakeEvidenceProvider" : evidence.source),
    ]);
  }

  function evidenceItem(label, value) {
    return h("div", { className: "evidence-item" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
    ]);
  }

  function agentFlowCard(agentName, scenario, session) {
    const meta = AGENT_META[agentName];
    const selected = state.selectedAgent === agentName;
    const summary = agentSummary(agentName, scenario, session);
    return h("button", {
      className: `agent-node tone-${meta.tone}${selected ? " is-selected" : ""}`,
      type: "button",
      onClick: () => selectAgent(agentName),
      "aria-pressed": selected ? "true" : "false",
    }, [
      h("span", { className: "agent-node-top" }, [
        h("strong", { text: meta.short }),
        h("small", { text: meta.phase }),
      ]),
      h("span", { className: "agent-node-summary", text: summary }),
    ]);
  }

  function agentSummary(agentName, scenario, session) {
    const action = actionFor(scenario, session);
    const diagnosis = diagnosisFor(scenario, session);
    if (agentName === "AIServiceHASupportAgent") {
      return `${diagnosis.severity} · ${diagnosis.cause}`;
    }
    if (agentName === "AIApplicationManagementAgent") {
      return actionLabel(action);
    }
    if (agentName === "AISemiconductorInfraOpsAgent") {
      return action.kind === "scale_out"
        ? `Replica ${action.replicas || 3} 수용 가능`
        : "자원 안전성 승인";
    }
    return action.kind === "scale_out" ? "비용 범위 내 승인" : "과잉 대응 없음";
  }

  function flowBlock(label, value, note) {
    return h("div", { className: "flow-block" }, [
      h("span", { text: label }),
      h("strong", { text: value }),
      note ? h("small", { text: note }) : null,
    ]);
  }

  function metricChart(scenario) {
    const values = scenario.chart || FALLBACK_SCENARIOS[0].chart;
    const width = 720;
    const height = 92;
    const pad = 4;
    const max = Math.max(...values, scenario.threshold, 1);
    const points = values.map((value, index) => {
      const x = pad + (index / (values.length - 1)) * (width - pad * 2);
      const y = height - pad - (value / max) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const thresholdY = height - pad - (scenario.threshold / max) * (height - pad * 2);

    return h("div", { className: "metric-chart" }, [
      h("div", { className: "chart-heading" }, [
        h("span", { text: `${scenario.label} · 최근 관측 흐름` }),
        h("strong", { text: metricHeadline(scenario, scenario.value) }),
      ]),
      svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${scenario.label} metric chart` }, [
        svg("line", {
          x1: pad,
          y1: thresholdY.toFixed(1),
          x2: width - pad,
          y2: thresholdY.toFixed(1),
          class: "threshold-line",
        }),
        svg("polyline", {
          points,
          class: "metric-line",
          fill: "none",
        }),
      ]),
    ]);
  }

  function decisionInspector(scenario, session) {
    const agentName = state.selectedAgent;
    const meta = AGENT_META[agentName];
    const diagnosis = diagnosisFor(scenario, session);
    const action = actionFor(scenario, session);
    const contribution = contributionFor(agentName, session);
    const safety = stagePayload(session, "safety");
    const matchingReviews = reviewsFor(session).filter((review) =>
      review.reviewer === agentName || review.target_agent === agentName
    );

    return h("section", { className: "decision-inspector" }, [
      h("div", { className: "inspector-heading" }, [
        h("div", {}, [
          h("p", { className: "eyebrow", text: "DECISION INSPECTOR" }),
          h("h2", { text: `${meta.short} 판단` }),
        ]),
        h("span", { className: "focus-icon", text: "⌗" }),
      ]),
      h("div", { className: "inspector-layout" }, [
        h("div", { className: "inspector-summary" }, [
          inspectorRow("진단 Cause", agentName === "AIServiceHASupportAgent" ? diagnosis.cause : meta.scope),
          inspectorRow("Severity", diagnosis.severity),
          inspectorRow("Confidence", formatDecimal(diagnosis.confidence || 0.88)),
          inspectorRow("Veto scope", meta.scope),
          inspectorRow("Reward", `+${formatDecimal(contribution.reward || defaultReward(agentName))}`),
        ]),
        h("div", { className: "inspector-detail" }, [
          inspectorSection("AGENT STATEMENT", agentStatement(agentName, scenario, action, diagnosis)),
          inspectorSection(
            "PEER REVIEWS",
            matchingReviews.length
              ? matchingReviews.map((review) =>
                `${shortAgent(review.reviewer)} → ${shortAgent(review.target_agent)} · ${review.verdict}`
              ).join("\n")
              : defaultPeerReviews(agentName, scenario, action).join("\n"),
          ),
          inspectorSection(
            "EXECUTION BOUNDARY",
            [
              `Allowlist  ${scenario.namespace}/${scenario.deployment}`,
              "Replica limit  1–5",
              `Guard  ${session ? session.guard_backend : state.backend}`,
              `Validation  ${safety.valid === true ? "통과" : "대기"}`,
            ].join("\n"),
          ),
        ]),
      ]),
      session
        ? h("div", { className: "command-preview" }, [
          h("span", { text: "검증된 명령" }),
          h("code", { text: safety.command || "observe_only" }),
        ])
        : null,
    ]);
  }

  function inspectorRow(label, value) {
    return h("div", { className: "inspector-row" }, [
      h("span", { text: label }),
      h("strong", { text: String(value) }),
    ]);
  }

  function inspectorSection(label, text) {
    return h("section", { className: "inspector-section" }, [
      h("span", { text: label }),
      h("p", { text }),
    ]);
  }

  function experimentTimeline(session) {
    const stages = [
      ["01", "조건", "시나리오·정책 고정", "condition"],
      ["02", "Evidence", "Metric·K8s 상태", "evidence"],
      ["03", "Agent 판단", "역할별 진단·제안", "diagnosis"],
      ["04", "상호검토", "거부권·재협상", "consensus"],
      ["05", "안전 검증", "Validator·Guard", "safety"],
      ["06", "실행", "Bounded Action", "execution"],
      ["07", "복구 평가", "결과·Reward", "result"],
    ];
    return h("section", { className: "experiment-timeline" }, [
      h("div", { className: "timeline-heading" }, [
        h("p", { className: "eyebrow", text: "EXPERIMENT SESSION" }),
        h("strong", { text: session ? session.experiment_id : "실행 전 연구 프로토콜" }),
      ]),
      h("div", { className: "timeline-steps" }, stages.map(([index, label, note, key]) => {
        const status = session?.stages?.[key]?.status || "pending";
        return h("div", { className: `timeline-step is-${status}` }, [
          h("span", { text: index }),
          h("div", {}, [
            h("strong", { text: label }),
            h("small", { text: note }),
          ]),
        ]);
      })),
    ]);
  }

  function consoleFooter(session) {
    return h("footer", { className: "console-footer" }, [
      h("span", {
        text: "웹 콘솔은 FakeEvidenceProvider 기반 mock 연구 경로입니다. 실제 Kubernetes real 제어는 CLI 안전 절차로 분리됩니다.",
      }),
      h("span", {
        text: session ? `Guard: ${session.guard_backend}` : "Python Validator + 선택적 Go Guard",
      }),
    ]);
  }

  function researchDocuments() {
    return h("section", { className: "research-documents" }, [
      h("div", { className: "document-heading" }, [
        h("div", {}, [
          h("p", { className: "eyebrow", text: "RESEARCH ARTIFACTS" }),
          h("strong", { text: "연구 문서" }),
        ]),
        h("span", { text: "실험 근거와 정책 명세" }),
      ]),
      h("div", { className: "document-links" }, RESEARCH_DOCUMENTS.map((document) =>
        h("a", {
          href: `/api/artifacts/${document.path}`,
          target: "_blank",
          rel: "noopener",
          title: document.sourcePath,
        }, [
          h("span", { className: "document-type", text: "DOCX" }),
          h("strong", { text: document.label }),
          h("small", { text: document.sourcePath }),
        ])
      )),
    ]);
  }

  function normalizedScenario(item) {
    const fallback = FALLBACK_SCENARIOS.find((scenario) => scenario.scenario_id === item.scenario_id) || {};
    return { ...fallback, ...item, summary: fallback.summary || item.summary };
  }

  function selectScenario(scenarioId) {
    if (
      state.currentSession
      && state.currentSession.condition
      && state.currentSession.condition.scenario !== scenarioId
    ) {
      state.currentSession = null;
    }
    state.selectedScenario = scenarioId;
    state.selectedAgent = "AIServiceHASupportAgent";
    state.lastError = "";
    render();
  }

  function selectAgent(agentName) {
    state.selectedAgent = agentName;
    render();
  }

  async function runScenario() {
    state.running = true;
    state.lastError = "";
    render();
    try {
      const response = await fetch("/api/experiments/mock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario_id: state.selectedScenario,
          backend: state.backend,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "실험 실행 요청이 거부되었습니다.");
      }
      state.currentSession = payload;
      state.experimentHistory = [
        payload,
        ...state.experimentHistory.filter((item) => item.experiment_id !== payload.experiment_id),
      ].slice(0, 8);
    } catch (error) {
      state.lastError = String(error.message || error);
    } finally {
      state.running = false;
      render();
    }
  }

  async function boot() {
    try {
      const [overviewResponse, agentsResponse, scenariosResponse, latestResponse] = await Promise.all([
        fetch("/api/overview"),
        fetch("/api/agents"),
        fetch("/api/scenarios"),
        fetch("/api/runs/latest"),
      ]);
      state.overview = overviewResponse.ok ? await overviewResponse.json() : null;
      state.agents = agentsResponse.ok ? (await agentsResponse.json()).agents || [] : [];
      const scenarioPayload = scenariosResponse.ok ? await scenariosResponse.json() : {};
      state.scenarios = scenarioPayload.scenarios?.length
        ? scenarioPayload.scenarios.map(normalizedScenario)
        : FALLBACK_SCENARIOS;
      state.latestRun = latestResponse.ok ? await latestResponse.json() : null;
    } catch (error) {
      state.lastError = `Control Plane API 연결 실패: ${String(error.message || error)}`;
    }
    render();
  }

  function metadataRow(label, value) {
    return h("div", { className: "metadata-row" }, [
      h("span", { text: label }),
      h("strong", { text: String(value) }),
    ]);
  }

  function metricHeadline(scenario, value) {
    if (scenario.metric === "latency") return `${Math.round(Number(value) * 1000)} ms`;
    if (scenario.metric === "availability") return `${value} / ${scenario.threshold}`;
    return `${Number(value).toFixed(1)}% ${scenario.metric.toUpperCase()}`;
  }

  function metricDisplay(scenario, value) {
    if (scenario.metric === "latency") return `${Math.round(Number(value) * 1000)}ms`;
    if (scenario.metric === "availability") return String(value);
    return `${Number(value).toFixed(1)}%`;
  }

  function thresholdLabel(scenario) {
    if (scenario.metric === "latency") return `${Math.round(scenario.threshold * 1000)}ms`;
    if (scenario.metric === "availability") return String(scenario.threshold);
    return `${scenario.threshold}%`;
  }

  function actionLabel(action) {
    if (!action || !action.kind) return "observe_only";
    return action.kind === "scale_out"
      ? `scale_out → ${action.replicas || 3}`
      : action.kind;
  }

  function statusLabel(status) {
    const labels = {
      recovered: "복구 성공",
      recovered_after_replan: "재계획 후 복구",
      no_action_required: "조치 불필요",
      safe_failure: "안전 중단",
      safe_stopped: "안전 중단",
    };
    return labels[status] || status || "대기";
  }

  function formatDecimal(value) {
    return Number(value || 0).toFixed(2);
  }

  function defaultReward(agentName) {
    return {
      AIServiceHASupportAgent: 0.9,
      AIApplicationManagementAgent: 0.85,
      AISemiconductorInfraOpsAgent: 0.7,
      CostOptimizationAgent: 0.6,
    }[agentName];
  }

  function shortAgent(agentName) {
    return AGENT_META[agentName]?.code || agentName;
  }

  function agentStatement(agentName, scenario, action, diagnosis) {
    if (agentName === "AIServiceHASupportAgent") {
      return `${scenario.label} Evidence에서 ${diagnosis.cause} 위험을 확인했습니다. 복구 필요성을 ${diagnosis.severity}로 판단합니다.`;
    }
    if (agentName === "AIApplicationManagementAgent") {
      return `진단 결과에 따라 ${actionLabel(action)} Action을 제안합니다. 허용된 실행 범위 안에서만 전달합니다.`;
    }
    if (agentName === "AISemiconductorInfraOpsAgent") {
      return action.kind === "scale_out"
        ? `Replica ${action.replicas || 3}은 정책 범위 1–5 안이며 인프라 용량 제약을 충족합니다.`
        : "제안된 Action은 Replica와 자원 안전성 정책을 위반하지 않습니다.";
    }
    return action.kind === "scale_out"
      ? "Replica 증가는 비용 한도 안에 있으며 과잉 대응으로 판단되지 않습니다."
      : "추가 자원 비용이 발생하지 않아 비용 정책 범위 안에서 승인합니다.";
  }

  function defaultPeerReviews(agentName, scenario, action) {
    const lines = {
      AIServiceHASupportAgent: [
        `APP  ${actionLabel(action)} 제안`,
        "INFRA  자원 안전성 검토",
        "COST  비용 정책 검토",
      ],
      AIApplicationManagementAgent: [
        `HA  ${scenario.label} 진단 근거 확인`,
        "INFRA  실행 가능성 승인",
        "COST  과잉 대응 여부 확인",
      ],
      AISemiconductorInfraOpsAgent: [
        `APP  ${actionLabel(action)} 수용성 요청`,
        "HA  복구 목표 일치 확인",
        "COST  자원 증가 한도 확인",
      ],
      CostOptimizationAgent: [
        `APP  ${actionLabel(action)} 비용 검토 요청`,
        "INFRA  용량 정책 충족",
        "HA  가용성 우선순위 확인",
      ],
    };
    return lines[agentName] || [];
  }

  boot();
})();
